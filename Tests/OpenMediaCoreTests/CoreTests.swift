import Foundation
import Testing
import Darwin
@testable import OpenMediaCore

struct ModelTests {
    @Test func testFramingSplitUnicodeCRLFAndFinalLine() {
        var framer = LineFramer()
        let bytes = Array("Größe\r\nOMD_EVENT:{\"type\":\"completed\"}\nEnde".utf8)
        var result: [String] = []
        for byte in bytes { result += framer.append(Data([byte])) }
        result += framer.append(Data(), endOfFile: true)
        #expect(result == ["Größe", "OMD_EVENT:{\"type\":\"completed\"}", "Ende"])
    }

    @Test func testVariantKeyIncludesMediaQualityAndMode() {
        let entry = MediaEntry(url: "https://example.org/video", title: "Test")
        let base = DownloadTask(entry: entry)
        let audio = DownloadTask(entry: entry, media: .aac)
        let resolution = DownloadTask(entry: entry, quality: "720")
        let mode = DownloadTask(entry: entry, mode: .chunks)
        #expect(Set([base, audio, resolution, mode].map(\.variantKey)).count == 4)
        #expect(base.variantKey == DownloadTask(entry: entry).variantKey)
    }

    @Test func testSizeDoesNotTreatUnknownAsZeroAndMatchesMode() {
        let estimates = [SizeEstimate(media: .video, quality: "720", bytes: 1000, approximate: true), SizeEstimate(media: .video, quality: "720", mode: .direct, bytes: 1100, approximate: false)]
        let entry = MediaEntry(url: "https://example.org/1", title: "Test", estimates: estimates)
        let tasks = [DownloadTask(entry: entry, quality: "720"), DownloadTask(entry: entry, quality: "720", mode: .direct), DownloadTask(entry: entry, media: .aac)]
        let total = QueueSize(tasks: tasks)
        #expect(total.knownBytes == 2100)
        #expect(total.unknownCount == 1)
        #expect(total.approximate)
        #expect(tasks[2].estimatedBytes == nil)
    }

    @Test func testDecodeMinimalEntryAndProgress() throws {
        let entry = try JSONDecoder().decode(MediaEntry.self, from: Data(#"{"url":"https://example.org/1","title":"Test"}"#.utf8))
        #expect(entry.availability == .unknown)
        #expect(entry.estimates == [])
        let event = BackendEvent.parse(#"OMD_EVENT:{"type":"progress","progress":0.5,"fragmentIndex":7,"fragmentCount":20}"#)
        #expect(event?.progress == 0.5)
        #expect(event?.fragmentIndex == 7)
        #expect(BackendEvent.parse("ordinary output") == nil)
    }

    @Test func testDecodeCookieFallbackWarningsAndEvents() throws {
        let json = #"{"ok":true,"warnings":[{"code":"browserCookieAccessDenied","browser":"safari","fallback":"withoutCookies"}],"cookieFallbackUsed":true}"#
        let response = try JSONDecoder().decode(InspectionResponse.self, from: Data(json.utf8))
        #expect(response.cookieFallbackUsed == true)
        #expect(response.warnings?.first?.code == "browserCookieAccessDenied")
        #expect(response.warnings?.first?.browser == "safari")
        #expect(response.warnings?.first?.fallback == "withoutCookies")
        let event = BackendEvent.parse(#"OMD_EVENT:{"type":"stage","stage":"preparing","code":"browserCookieAccessDenied","fallback":"withoutCookies"}"#)
        #expect(event?.fallback == "withoutCookies")
    }

    @Test func testQualityListsKeepAudioAndVideoSeparate() {
        #expect(QualityOptions.values(for: .video).contains("4320"))
        #expect(!QualityOptions.values(for: .video).contains("320k"))
        #expect(QualityOptions.values(for: .aac) == ["best"])
    }

    @Test func testEstimateNeverUsesAnotherMediaOrTransferMode() {
        let entry = MediaEntry(url: "https://example.org/1", title: "Test", estimates: [
            SizeEstimate(media: .video, quality: "best", bytes: 20_000, approximate: true),
            SizeEstimate(media: .aac, quality: "best", bytes: 4_000, approximate: true),
            SizeEstimate(media: .mp3, quality: "192k", mode: .chunks, bytes: 3_000, approximate: true)
        ])
        #expect(DownloadTask(entry: entry, media: .aac).estimatedBytes == 4_000)
        #expect(DownloadTask(entry: entry, media: .aac, mode: .direct).estimatedBytes == nil)
        #expect(DownloadTask(entry: entry, media: .mp3, quality: "192k", mode: .chunks).estimatedBytes == 3_000)
    }
}

@MainActor
struct CoordinatorTests {
    private func waitUntil(_ predicate: @MainActor () -> Bool, sourceLocation: SourceLocation = #_sourceLocation) async {
        for _ in 0..<200 {
            if predicate() { return }
            try? await Task.sleep(nanoseconds: 5_000_000)
        }
        Issue.record("Timed out", sourceLocation: sourceLocation)
    }

    private func prepared(count: Int) async -> (DownloadCoordinator, FakeBackend) {
        let backend = FakeBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        coordinator.updateInput((0..<count).map { "https://example.org/video/\($0)" }.joined(separator: "\n"))
        await waitUntil { coordinator.rows.count == count && !coordinator.isInspecting }
        return (coordinator, backend)
    }

    @Test func testSchedulerStartsFourIndependentDownloadsAndRefillsAfterCancel() async {
        let (coordinator, backend) = await prepared(count: 6)
        coordinator.startDownloads()
        #expect(coordinator.authPrompt != nil)
        #expect(backend.downloads.count == 0)
        coordinator.resolveAuthentication(.anonymous)
        #expect(backend.downloads.count == 4)
        #expect(coordinator.activeCount == 4)
        #expect(coordinator.queuedCount == 2)
        let first = coordinator.rows[0].id
        coordinator.removeOrCancel(first)
        await waitUntil { backend.downloads.count == 5 }
        #expect(coordinator.activeCount == 4)
        #expect(coordinator.rows.first { $0.id == first }?.stage == .cancelled)
        coordinator.cancelAll()
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.batchSummary?.cancelled == 6)
        #expect(backend.downloads.allSatisfy { $0.run.wasCancelled })
    }

    @Test func testExactVariantsAreDeduplicatedButAudioAndVideoRemainParallel() async {
        let (coordinator, backend) = await prepared(count: 1)
        let id = coordinator.rows[0].id
        coordinator.addVariant(for: id)
        coordinator.addVariant(for: id)
        coordinator.updateVariant(coordinator.rows[2].id, media: .aac)
        coordinator.addVariant(for: id)
        coordinator.updateVariant(coordinator.rows[3].id, media: .mp3)
        coordinator.resolveAuthentication(.anonymous)
        coordinator.startDownloads()
        #expect(coordinator.rows.count == 3)
        #expect(backend.downloads.count == 3)
        #expect(Set(coordinator.rows.map(\.media)) == [.video, .aac, .mp3])
        #expect(coordinator.rows.first { $0.media == .mp3 }?.quality == "320k")
        #expect(Set(backend.downloads.map { $0.arguments.last! }) == ["https://example.org/video/0"])
        #expect(backend.downloads.allSatisfy { !$0.run.wasCancelled })
        for call in backend.downloads { call.run.emit(#"OMD_EVENT:{"type":"completed","path":"/tmp/result.mp4"}"#); call.run.finish(0) }
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.batchSummary?.completed == 3)
    }

    @Test func testDefaultsUseFourFilesAndFourFragments() async {
        let (coordinator, backend) = await prepared(count: 5)
        #expect(coordinator.maxConcurrentFiles == 4)
        #expect(coordinator.fragmentsPerFile == 4)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        #expect(backend.downloads.count == 4)
        #expect(backend.downloads.allSatisfy { call in
            guard let index = call.arguments.firstIndex(of: "--workers") else { return false }
            return call.arguments[index + 1] == "4"
        })
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testLiveRecordingForwardsStableTaskID() async {
        let backend = FakeBackend(inspectionStreamState: "live")
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        coordinator.updateInput("https://example.org/live")
        await waitUntil { coordinator.rows.count == 1 && !coordinator.isInspecting }
        let rowID = coordinator.rows[0].id

        coordinator.resolveAuthentication(.anonymous)
        coordinator.startDownloads()

        #expect(backend.downloads.count == 1)
        let arguments = backend.downloads[0].arguments
        guard let taskIDIndex = arguments.firstIndex(of: "--task-id") else {
            Issue.record("Live recording command is missing --task-id")
            coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
            return
        }
        #expect(arguments.contains("--record-stream"))
        #expect(taskIDIndex + 1 < arguments.count)
        if taskIDIndex + 1 < arguments.count {
            #expect(arguments[taskIDIndex + 1] == rowID.uuidString)
        }
        coordinator.stopAndSave(rowID)
        #expect(backend.downloads[0].run.inputs == ["stop\n"])
        #expect(coordinator.rows[0].stage == .finalizing)
        backend.downloads[0].run.emit(#"OMD_EVENT:{"type":"progress","downloadedBytes":123}"#)
        #expect(coordinator.rows[0].stage == .finalizing)
        backend.downloads[0].run.emit(#"OMD_EVENT:{"type":"stage","stage":"live"}"#)
        #expect(coordinator.rows[0].stage == .finalizing)
        backend.downloads[0].run.finish(0)
        await waitUntil { !coordinator.isRunning }
    }

    @Test func testForceStopAllCancelsRecordingWithoutReplacingGracefulStop() async {
        let backend = FakeBackend(inspectionStreamState: "live")
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        coordinator.updateInput("https://example.org/live")
        await waitUntil { coordinator.rows.count == 1 && !coordinator.isInspecting }
        coordinator.resolveAuthentication(.anonymous)
        coordinator.startDownloads()
        #expect(backend.downloads.count == 1)

        coordinator.forceStopAll()

        #expect(backend.downloads[0].run.wasCancelled)
        #expect(backend.downloads[0].run.inputs.isEmpty)
        await waitUntil { !coordinator.hasActiveWork }
        #expect(coordinator.rows[0].stage == .cancelled)
    }

    @Test func testOverwritePromptsRouteToCorrectSeparateProcesses() async {
        let (coordinator, backend) = await prepared(count: 2)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let calls = backend.downloads
        calls[0].run.emit(#"OMD_EVENT:{"type":"overwrite","path":"/tmp/first.mp4"}"#)
        calls[1].run.emit(#"OMD_EVENT:{"type":"overwrite","path":"/tmp/second.mp4"}"#)
        await waitUntil { coordinator.overwritePrompt != nil && coordinator.rows.allSatisfy { $0.stage == .waitingForOverwrite } }
        let firstPrompt = coordinator.overwritePrompt!
        coordinator.answerOverwrite(false)
        #expect(firstPrompt.taskID != coordinator.overwritePrompt?.taskID)
        coordinator.answerOverwrite(true)
        #expect(coordinator.overwritePrompt == nil)
        #expect(calls.flatMap { $0.run.inputs }.sorted() == ["n\n", "y\n"])
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testProgressAndErrorAreFinalOnlyAfterOutputAndExit() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let run = backend.downloads[0].run
        run.emit(#"OMD_EVENT:{"type":"progress","progress":0.35,"fragmentIndex":7,"fragmentCount":20,"speedBytesPerSecond":1000,"totalBytes":10000,"etaSeconds":6}"#)
        await waitUntil { coordinator.rows[0].progress.fraction == 0.35 }
        #expect(coordinator.rows[0].progress.fragmentCount == 20)
        run.emit(#"OMD_EVENT:{"type":"error","code":"authenticationRequired","message":"Login required"}"#)
        run.emit(#"OMD_EVENT:{"type":"progress","progress":0.9}"#)
        run.finish(1)
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.rows[0].stage == .authenticationRequired)
        #expect(coordinator.batchSummary?.authenticationRequired == 1)
    }

    @Test func testCancelledTaskNeverBecomesCompletedFromBufferedEvent() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let run = backend.downloads[0].run
        run.emit(#"OMD_EVENT:{"type":"completed","path":"/tmp/test.mp4"}"#)
        coordinator.removeOrCancel(coordinator.rows[0].id)
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.rows[0].stage == .cancelled)
    }

    @Test func testDebounceAndInputDeduplication() async {
        let backend = FakeBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 20_000_000)
        coordinator.updateInput("https://example.org/wrong")
        coordinator.updateInput("https://example.org/right\nhttps://example.org/right")
        await waitUntil { coordinator.rows.count == 1 && !coordinator.isInspecting }
        #expect(backend.calls.count == 1)
        #expect(coordinator.rows[0].url == "https://example.org/right")
        #expect(DownloadCoordinator.extractURLs(from: "javascript:alert(1) file:///tmp/test") == [])
    }

    @Test func testPlaylistVariantsKeepUserSelectionAndUnknownSizes() async {
        let backend = FakeBackend(playlist: true)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/playlist"
        coordinator.inspectInput()
        await waitUntil { coordinator.playlistGroups.count == 1 }
        let group = coordinator.playlistGroups[0]
        coordinator.addPlaylistSelection(groupID: group.id, variants: [PlaylistSelection(entryID: group.entries[0].id), PlaylistSelection(entryID: group.entries[0].id, media: .aac)])
        #expect(coordinator.rows.count == 2)
        #expect(coordinator.playlistGroups.isEmpty)
        #expect(coordinator.unknownEstimateCount == 2)
    }

    @Test func testEmbedOriginSurvivesPlaylistSelectionAndDownloadArguments() async {
        let backend = FakeBackend(playlist: true, embedRefererOrigin: "https://final.publisher.example:8443/")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://publisher.example/start"
        coordinator.inspectInput()
        await waitUntil { coordinator.playlistGroups.count == 1 }
        let group = coordinator.playlistGroups[0]
        coordinator.addPlaylistSelection(groupID: group.id, variants: [PlaylistSelection(entryID: group.entries[0].id), PlaylistSelection(entryID: group.entries[0].id, media: .aac)])
        #expect(coordinator.rows.count == 2)
        #expect(coordinator.rows.allSatisfy { $0.embedRefererOrigin == "https://final.publisher.example:8443/" })
        coordinator.startDownloads()
        coordinator.resolveAuthentication(.anonymous)
        #expect(backend.downloads.count == 2)
        #expect(backend.downloads.allSatisfy { call in call.arguments.indices.contains { index in call.arguments[index] == "--referer" && call.arguments.index(after: index) < call.arguments.endIndex && call.arguments[call.arguments.index(after: index)] == "https://final.publisher.example:8443/" } })
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testSeparateFragmentCountIsForwardedAndFileLimitIsRespected() async {
        let (coordinator, backend) = await prepared(count: 4)
        coordinator.maxConcurrentFiles = 2; coordinator.fragmentsPerFile = 7
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        #expect(backend.downloads.count == 2)
        for call in backend.downloads {
            let index = call.arguments.firstIndex(of: "--workers")!
            #expect(call.arguments[index + 1] == "7")
        }
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testSanitizerHidesSecretsAndCookiePaths() {
        let cleaned = DownloadCoordinator.sanitize("https://example.org/?token=secret&x=1 /Users/Alice/Library/Cookies/private")
        #expect(!cleaned.contains("secret"))
        #expect(!cleaned.contains("Alice"))
    }

    @Test func testSanitizerHidesEverySignedQueryKeyAndEncodedNames() {
        let keys = ["access_token", "token", "password", "signature", "sig", "auth", "key", "jwt", "policy", "h", "%68", "ACCESS_TOKEN"]
        for key in keys {
            let cleaned = DownloadCoordinator.sanitize("https://example.org/video?id=123&\(key)=SYNTHETIC-PRIVATE-VALUE&quality=720")
            #expect(!cleaned.contains("SYNTHETIC-PRIVATE-VALUE"))
            #expect(cleaned.contains("id=123"))
            #expect(cleaned.contains("quality=720"))
        }
        #expect(!DownloadCoordinator.sanitize("https://USERNAME:PASSWORD@example.org/video").contains("PASSWORD"))
        #expect(!DownloadCoordinator.sanitize("https://vimeo.com/123456/SYNTHETIC-UNLISTED").contains("SYNTHETIC-UNLISTED"))
    }

    @Test func testInspectionErrorLogNeverIncludesPrivateURLParameters() async {
        let backend = FakeBackend(requiresAuthentication: true)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://vimeo.com/123456/SYNTHETIC-PATH?h=SYNTHETIC-HASH&auth=SYNTHETIC-AUTH&policy=SYNTHETIC-POLICY"
        coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows.first?.stage == .authenticationRequired)
        #expect(!coordinator.logLines.isEmpty)
        #expect(!coordinator.logLines.joined().contains("SYNTHETIC"))
        #expect(coordinator.logLines.joined().contains("vimeo.com/123456/"))
    }

    @Test func testCookieFallbackFromInspectionAndDownloadsIsVisibleOnlyOnce() async {
        let backend = FakeBackend(inspectionCookieFallback: true)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/one\nhttps://example.org/two"
        coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows.count == 2)
        #expect(coordinator.logLines.filter { $0 == "cookiesFallbackWithoutAuthentication" }.count == 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        for call in backend.downloads {
            call.run.emit(#"OMD_EVENT:{"type":"stage","stage":"preparing","code":"browserCookieAccessDenied","fallback":"withoutCookies","message":"Cookie: SYNTHETIC-PRIVATE-VALUE"}"#)
            call.run.emit(#"OMD_EVENT:{"type":"completed"}"#); call.run.finish(0)
        }
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.logLines.filter { $0 == "cookiesFallbackWithoutAuthentication" }.count == 1)
        #expect(!coordinator.logLines.joined().contains("SYNTHETIC"))
        #expect(coordinator.rows.allSatisfy { $0.stage == .completed })
    }

    @Test func testDownloadOnlyCookieFallbackIsVisibleAndDoesNotFailTask() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let run = backend.downloads[0].run
        run.emit(#"OMD_EVENT:{"type":"stage","stage":"preparing","code":"browserCookieAccessDenied","fallback":"withoutCookies"}"#)
        run.emit(#"OMD_EVENT:{"type":"completed"}"#); run.finish(0)
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.logLines.filter { $0 == "cookiesFallbackWithoutAuthentication" }.count == 1)
        #expect(coordinator.rows.first?.stage == .completed)
    }

    @Test func testPublicAccessRetryResetsProgressAndKeepsCompletionSuccessful() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let run = backend.downloads[0].run
        run.emit(#"OMD_EVENT:{"type":"progress","progress":0.8,"downloadedBytes":80,"totalBytes":100,"fragmentIndex":8,"fragmentCount":10}"#)
        await waitUntil { coordinator.rows.first?.progress.fraction == 0.8 }
        run.emit(#"OMD_EVENT:{"type":"stage","stage":"preparing","code":"publicAccessFallback","fallback":"withoutCookies","message":"Cookie: SYNTHETIC-SECRET"}"#)
        await waitUntil { coordinator.logLines.contains("publicAccessFallback") }
        #expect(coordinator.rows.first?.progress == DownloadProgress())
        #expect(coordinator.rows.first?.stage == .preparing)
        #expect(!coordinator.logLines.joined().contains("SYNTHETIC"))
        run.emit(#"OMD_EVENT:{"type":"completed"}"#); run.finish(0)
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.rows.first?.stage == .completed)
        #expect(coordinator.rows.first?.errorCode == nil)
    }

    @Test func testCancelBeforeStartDoesNotRestartWithoutExplicitRetry() async {
        let (coordinator, backend) = await prepared(count: 2)
        #expect(coordinator.hasCancellableWork)
        coordinator.cancelAll()
        #expect(coordinator.rows.allSatisfy { $0.stage == .cancelled })
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        #expect(backend.downloads.isEmpty)
        coordinator.retry(coordinator.rows[0].id); coordinator.startDownloads()
        #expect(backend.downloads.count == 1)
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testPublicOnlyRetainsButDoesNotDownloadKnownAuthRequiredRows() async {
        let backend = FakeBackend(requiresAuthentication: true)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/private"
        coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows[0].stage == .authenticationRequired)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        #expect(backend.downloads.isEmpty)
        #expect(coordinator.batchSummary?.authenticationRequired == 1)
    }

    @Test func testBrowserReadOnceAndPrivateCookieSnapshotReusedForFourDownloads() async {
        let backend = FakeBackend(authStatus: "ready")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = (0..<4).map { "https://example.org/\($0)" }.joined(separator: "\n")
        coordinator.inspectInput(); await waitUntil { !coordinator.isInspecting }
        coordinator.startDownloads(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { backend.downloads.count == 4 }
        let authCalls = backend.calls.filter { $0.arguments.contains("--auth-check-json") }
        #expect(authCalls.count == 1)
        let paths = backend.downloads.compactMap { call -> String? in
            guard let index = call.arguments.firstIndex(of: "--cookies-file") else { return nil }
            #expect(!call.arguments.contains("--cookies-browser"))
            return call.arguments[index + 1]
        }
        #expect(paths.count == 4)
        #expect(Set(paths).count == 1)
        #expect(FileManager.default.isReadableFile(atPath: paths[0]))
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
        coordinator.shutdown()
        #expect(!FileManager.default.fileExists(atPath: paths[0]))
    }

    @Test func testEmptyValidCookiesResolveAsAnonymous() async {
        let backend = FakeBackend(authStatus: "anonymous")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.requestAuthentication(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating }
        #expect(coordinator.authenticationStatus == "anonymous")
        #expect(coordinator.authPrompt == nil)
    }

    @Test func testAdditionalAuthDomainsIncludeOnlySortedNonMediaSourceHosts() async {
        let backend = FakeBackend()
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = [
            "https://zeta.example.org/watch", "https://www.youtube.com/watch?v=x",
            "https://sub.googlevideo.com/file", "https://vimeo.com/123",
            "https://alpha.example.net/video", "https://google.com/search",
            "https://youtube-nocookie.com/embed/x", "https://bad_host.example/video"
        ].joined(separator: "\n")
        coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.additionalAuthDomains == ["alpha.example.net", "zeta.example.org"])
    }

    @Test func testEmbeddedRefererUsesOnlyExternalSourceOrigin() async {
        #expect(DownloadCoordinator.embeddedRefererArguments(embedRefererOrigin: "https://publisher.example:8443/", sourceURL: "https://publisher.example/article", mediaURL: "https://www.youtube.com/embed/abc") == ["--referer", "https://publisher.example:8443/"])
        #expect(DownloadCoordinator.embeddedRefererArguments(embedRefererOrigin: nil, sourceURL: "https://youtube.com/watch?v=x", mediaURL: "https://youtube.com/watch?v=x").isEmpty)
        #expect(DownloadCoordinator.embeddedRefererArguments(embedRefererOrigin: "https://publisher.example/path?secret=x", sourceURL: "https://publisher.example/article", mediaURL: "https://www.youtube.com/embed/abc").isEmpty)
        #expect(DownloadCoordinator.embeddedRefererArguments(embedRefererOrigin: "https://publisher.example/", sourceURL: "https://publisher.example/article", mediaURL: "https://video.example/watch").isEmpty)
    }

    @Test func testExplicitCurrentAuthDomainsAreForwardedAsRepeatedArguments() async {
        let backend = FakeBackend(authStatus: "ready")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://zeta.example.org/watch\nhttps://alpha.example.net/video"
        coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        coordinator.resolveAuthentication(.browser("safari"), allowedDomains: ["zeta.example.org", "stale.example.com", "ALPHA.EXAMPLE.NET", "zeta.example.org"])
        await waitUntil { !coordinator.isAuthenticating }
        let args = backend.calls.first { $0.arguments.contains("--auth-check-json") }!.arguments
        var domains: [String] = []
        for index in args.indices where args[index] == "--auth-domain" { domains.append(args[args.index(after: index)]) }
        #expect(domains == ["alpha.example.net", "zeta.example.org"])
        coordinator.startDownloads()
        await waitUntil { backend.downloads.count == 2 }
        for call in backend.downloads {
            #expect(call.arguments.contains("alpha.example.net"))
            #expect(call.arguments.contains("zeta.example.org"))
            #expect(!call.arguments.contains("stale.example.com"))
        }
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testAnonymousAuthenticationNeverForwardsAuthDomains() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.startDownloads()
        coordinator.resolveAuthentication(.anonymous, allowedDomains: ["example.org"])
        #expect(backend.calls.allSatisfy { !$0.arguments.contains("--auth-domain") })
        coordinator.cancelAll()
        await waitUntil { !coordinator.isRunning }
    }

    @Test func testDeniedCookiesKeepChoiceOpenThenPublicCanContinue() async {
        let backend = FakeBackend(authStatus: "browserCookieAccessDenied")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/public"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        coordinator.startDownloads(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating }
        #expect(coordinator.authPrompt?.errorCode == "browserCookieAccessDenied")
        #expect(backend.downloads.isEmpty)
        coordinator.resolveAuthentication(.anonymous)
        #expect(backend.downloads.count == 1)
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testManualRecheckPreservesVariantsAndDoesNotAppendDuplicates() async {
        let (coordinator, _) = await prepared(count: 1)
        let id = coordinator.rows[0].id
        coordinator.updateVariant(id, media: .mp3, quality: "192k")
        coordinator.cancelAll()
        coordinator.inspectInput(force: true)
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows.count == 1)
        #expect(coordinator.rows[0].id == id)
        #expect(coordinator.rows[0].media == .mp3)
        #expect(coordinator.rows[0].quality == "192k")
        coordinator.inspectInput(force: true)
        #expect(coordinator.rows.count == 1)
    }

    @Test func testAuthenticationCancelKeepsRunAndPrivateSessionUntilExit() async {
        let backend = FakeBackend(authStatus: "ready", authAutomaticallyFinishes: false, finishesOnCancel: false)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.resolveAuthentication(.anonymous)
        coordinator.requestAuthentication(); coordinator.resolveAuthentication(.browser("safari"))
        let call = backend.calls[0]
        let path = call.arguments[call.arguments.firstIndex(of: "--session-dir")! + 1]
        coordinator.cancelAuthentication()
        #expect(coordinator.authPrompt == nil)
        #expect(coordinator.isAuthenticating)
        #expect(call.run.wasCancelled)
        #expect(FileManager.default.fileExists(atPath: path))
        coordinator.resolveAuthentication(.browser("chrome"))
        #expect(backend.calls.count == 1)
        call.run.finish(143)
        await waitUntil { !coordinator.isAuthenticating }
        #expect(coordinator.authenticationStatus == "anonymous")
        #expect(coordinator.authPrompt == nil)
        #expect(!FileManager.default.fileExists(atPath: path))
    }

    @Test func testAuthenticationBackendMessageIsDisplayed() async {
        let backend = FakeBackend(authStatus: "browserCookieAccessDenied", authMessage: "Browser access was denied")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.requestAuthentication(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating }
        #expect(coordinator.authPrompt?.message == "Browser access was denied")
    }

    @Test func testReadyAuthenticationRechecksKnownPrivateRowsBeforeStarting() async {
        let backend = FakeBackend(requiresAuthentication: true, authStatus: "ready", acceptsSnapshot: true)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/private"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        let rowID = coordinator.rows[0].id
        coordinator.startDownloads(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { backend.downloads.count == 1 }
        let checks = backend.calls.filter { $0.arguments.contains("--inspect-json") }
        #expect(checks.count == 2)
        #expect(!checks[0].arguments.contains("--cookies-file"))
        #expect(checks[1].arguments.contains("--cookies-file"))
        #expect(coordinator.rows.count == 1)
        #expect(coordinator.rows[0].id == rowID)
        #expect(coordinator.rows[0].title == "Example video")
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testStillPrivateAfterSnapshotIsNotImmediatelyDownloadedAgain() async {
        let backend = FakeBackend(requiresAuthentication: true, authStatus: "ready")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/private"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        coordinator.startDownloads(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating && !coordinator.isInspecting }
        #expect(backend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 2)
        #expect(backend.downloads.isEmpty)
        #expect(coordinator.rows[0].stage == .authenticationRequired)
        #expect(coordinator.batchSummary?.authenticationRequired == 1)
    }

    @Test func testNonzeroInspectionExitDoesNotAcceptEarlySuccessJSON() async {
        let backend = FakeBackend(inspectionExitCode: 7)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/public"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows[0].stage == .failed)
        #expect(coordinator.rows[0].errorCode == "inspectionFailed")
    }

    @Test func testInspectionCacheReusesFreshMetadataWithinContext() async {
        let backend = FakeBackend(authStatus: "ready")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/cache"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        let firstID = coordinator.rows[0].id
        coordinator.removeOrCancel(firstID)
        coordinator.inspectInput(force: true)
        #expect(backend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 1)
        #expect(coordinator.rows.last?.title == "Example video")
    }

    @Test func testExpiredInspectionCacheLaunchesFreshInspection() async {
        let backend = FakeBackend(inspectionTitles: ["Old title", "Fresh title"])
        let coordinator = DownloadCoordinator(client: backend, inspectionCacheLifetime: 0)
        coordinator.inputText = "https://example.org/cache"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        coordinator.removeOrCancel(coordinator.rows[0].id)
        coordinator.inspectInput(force: true)
        await waitUntil { !coordinator.isInspecting }
        #expect(backend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 2)
        #expect(coordinator.rows[0].title == "Fresh title")
    }

    @Test func testAuthorizationResolutionInvalidatesInspectionCache() async {
        let backend = FakeBackend(authStatus: "ready")
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/cache"; coordinator.inspectInput()
        await waitUntil { !coordinator.isInspecting }
        coordinator.removeOrCancel(coordinator.rows[0].id)
        coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating && coordinator.authenticationStatus == "ready" }
        coordinator.inspectInput(force: true)
        await waitUntil { !coordinator.isInspecting }
        let calls = backend.calls.filter { $0.arguments.contains("--inspect-json") }
        #expect(calls.count == 2)
        #expect(calls[1].arguments.contains("--cookies-file"))
    }

    @Test func testCancelledAndFailedInspectionsAreNotCached() async {
        let cancelledBackend = FakeBackend(finishesOnCancel: false, inspectionAutomaticallyFinishes: false)
        let cancelledCoordinator = DownloadCoordinator(client: cancelledBackend)
        cancelledCoordinator.inputText = "https://example.org/cancel"; cancelledCoordinator.inspectInput()
        cancelledCoordinator.removeOrCancel(cancelledCoordinator.rows[0].id)
        cancelledBackend.calls[0].run.finish(143)
        await waitUntil { !cancelledCoordinator.isInspecting }
        cancelledCoordinator.inspectInput(force: true)
        #expect(cancelledBackend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 2)
        cancelledBackend.calls[1].run.finish(0)
        await waitUntil { !cancelledCoordinator.isInspecting }

        let failedBackend = FakeBackend(inspectionExitCode: 7)
        let failedCoordinator = DownloadCoordinator(client: failedBackend)
        failedCoordinator.inputText = "https://example.org/failed"; failedCoordinator.inspectInput()
        await waitUntil { !failedCoordinator.isInspecting }
        failedCoordinator.inspectInput(force: true)
        await waitUntil { !failedCoordinator.isInspecting }
        #expect(failedBackend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 2)
        #expect(failedCoordinator.rows[0].stage == .failed)
    }

    @Test func testErrorCannotBeOverwrittenByLateCompletedEvent() async {
        let (coordinator, backend) = await prepared(count: 1)
        coordinator.resolveAuthentication(.anonymous); coordinator.startDownloads()
        let run = backend.downloads[0].run
        run.emit(#"OMD_EVENT:{"type":"error","code":"downloadFailed","message":"Failed"}"#)
        run.emit(#"OMD_EVENT:{"type":"completed","path":"/tmp/result.mp4"}"#)
        run.finish(0)
        await waitUntil { !coordinator.isRunning }
        #expect(coordinator.rows[0].stage == .failed)
        #expect(coordinator.batchSummary?.completed == 0)
    }

    @Test func testStartFlushesPendingInputDebounce() async {
        let backend = FakeBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 10_000_000_000)
        coordinator.resolveAuthentication(.anonymous)
        coordinator.updateInput("https://example.org/public")
        coordinator.startDownloads()
        await waitUntil { backend.downloads.count == 1 }
        #expect(coordinator.rows.count == 1)
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testCancelledInspectionCannotBeReplacedBeforeItsProcessExits() async {
        let backend = FakeBackend(finishesOnCancel: false, inspectionAutomaticallyFinishes: false)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/public"; coordinator.inspectInput()
        let id = coordinator.rows[0].id
        coordinator.removeOrCancel(id)
        coordinator.inspectInput(force: true)
        coordinator.updateVariant(id, media: .aac)
        #expect(backend.calls.count == 1)
        #expect(coordinator.rows[0].media == .video)
        backend.calls[0].run.finish(143)
        await waitUntil { !coordinator.isInspecting }
        coordinator.inspectInput(force: true)
        #expect(backend.calls.count == 2)
        backend.calls[1].run.finish(0)
        await waitUntil { !coordinator.isInspecting }
        #expect(coordinator.rows[0].id == id)
        #expect(coordinator.rows[0].stage == .queued)
    }

    @Test func testAnonymousInspectionFinishingAfterLoginRechecksWithSnapshot() async {
        let backend = FakeBackend(requiresAuthentication: true, authStatus: "ready", acceptsSnapshot: true, inspectionAutomaticallyFinishes: false)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.inputText = "https://example.org/private"; coordinator.inspectInput()
        let first = backend.calls[0]
        coordinator.requestAuthentication(); coordinator.resolveAuthentication(.browser("safari"))
        await waitUntil { !coordinator.isAuthenticating }
        coordinator.startDownloads()
        first.run.finish(1)
        await waitUntil { backend.calls.filter { $0.arguments.contains("--inspect-json") }.count == 2 }
        let second = backend.calls.last { $0.arguments.contains("--inspect-json") }!
        #expect(second.arguments.contains("--cookies-file"))
        second.run.finish(0)
        await waitUntil { backend.downloads.count == 1 }
        #expect(coordinator.rows.count == 1)
        coordinator.cancelAll(); await waitUntil { !coordinator.isRunning }
    }

    @Test func testReadyAuthPayloadWithFailedProcessExitIsNotAccepted() async {
        let backend = FakeBackend(authStatus: "ready", authAutomaticallyFinishes: false)
        let coordinator = DownloadCoordinator(client: backend)
        coordinator.resolveAuthentication(.browser("safari"))
        backend.calls[0].run.finish(7)
        await waitUntil { !coordinator.isAuthenticating }
        #expect(coordinator.authenticationStatus == "authenticationCheckFailed")
        #expect(coordinator.authPrompt?.errorCode == "authenticationCheckFailed")
    }
}

struct ProcessTests {
    @Test func testRealProcessDrainsOutputBeforeExit() async throws {
        let client = ProcessBackendClient(executable: URL(fileURLWithPath: "/bin/sh"))
        let run = try client.launch(arguments: ["-c", "printf 'Größe\\nOMD_EVENT:{\"type\":\"completed\"}'; exit 7"])
        var events: [BackendOutput] = []
        for await event in run.events { events.append(event) }
        #expect(events == [.line("Größe"), .line(#"OMD_EVENT:{"type":"completed"}"#), .exited(7)])
    }

    @Test func testExitedParentWithInheritedPipeDoesNotHangForever() async throws {
        let client = ProcessBackendClient(executable: URL(fileURLWithPath: "/usr/bin/python3"), outputDrainTimeout: 0.2)
        let code = "import os,subprocess,sys\ntry: os.setsid()\nexcept OSError: pass\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\nprint(p.pid,flush=True)"
        let start = Date()
        let run = try client.launch(arguments: ["-c", code])
        var status: Int32?
        var childPID: Int32?
        var hadDrainError = false
        for await event in run.events {
            switch event {
            case .line(let line):
                if let pid = Int32(line) { childPID = pid }
                if BackendEvent.parse(line)?.code == "backendOutputDidNotClose" { hadDrainError = true }
            case .exited(let value): status = value
            }
        }
        defer { if let childPID { _ = kill(childPID, SIGKILL) } }
        #expect(Date().timeIntervalSince(start) < 5)
        #expect(status != 0 && status != nil)
        #expect(childPID != nil)
        #expect(hadDrainError)
    }

    @Test func testCancelledProcessIsRetainedUntilForcedTermination() async throws {
        let client = ProcessBackendClient(executable: URL(fileURLWithPath: "/usr/bin/python3"))
        let code = "import os,signal,time\ntry: os.setsid()\nexcept OSError: pass\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nprint('ready',flush=True)\ntime.sleep(30)"
        var run: (any BackendRunning)? = try client.launch(arguments: ["-c", code])
        let events = run!.events
        let start = Date()
        var status: Int32?
        var sawReady = false
        for await event in events {
            switch event {
            case .line(let line): if line == "ready" { sawReady = true; run?.cancel(); run = nil }
            case .exited(let value): status = value
            }
        }
        #expect(Date().timeIntervalSince(start) < 6)
        #expect(sawReady)
        #expect(status != nil && status != 0)
    }
}

private struct FakeCall: Sendable { var arguments: [String]; var run: FakeRun }
private final class FakeBackend: BackendClient, @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [FakeCall] = []
    let playlist: Bool
    let requiresAuthentication: Bool
    let authStatus: String
    let authAutomaticallyFinishes: Bool
    let finishesOnCancel: Bool
    let acceptsSnapshot: Bool
    let inspectionExitCode: Int32
    let authMessage: String?
    let inspectionAutomaticallyFinishes: Bool
    let inspectionCookieFallback: Bool
    let inspectionTitles: [String]
    let inspectionStreamState: String?
    let embedRefererOrigin: String?
    init(playlist: Bool = false, requiresAuthentication: Bool = false, authStatus: String = "anonymous", authAutomaticallyFinishes: Bool = true, finishesOnCancel: Bool = true, acceptsSnapshot: Bool = false, inspectionExitCode: Int32 = 0, authMessage: String? = nil, inspectionAutomaticallyFinishes: Bool = true, inspectionCookieFallback: Bool = false, inspectionTitles: [String] = [], inspectionStreamState: String? = nil, embedRefererOrigin: String? = nil) {
        self.playlist = playlist; self.requiresAuthentication = requiresAuthentication; self.authStatus = authStatus
        self.authAutomaticallyFinishes = authAutomaticallyFinishes; self.finishesOnCancel = finishesOnCancel
        self.acceptsSnapshot = acceptsSnapshot; self.inspectionExitCode = inspectionExitCode; self.authMessage = authMessage
        self.inspectionAutomaticallyFinishes = inspectionAutomaticallyFinishes
        self.inspectionCookieFallback = inspectionCookieFallback
        self.inspectionTitles = inspectionTitles
        self.inspectionStreamState = inspectionStreamState
        self.embedRefererOrigin = embedRefererOrigin
    }
    var calls: [FakeCall] { lock.withLock { storage } }
    var downloads: [FakeCall] { calls.filter { !$0.arguments.contains("--inspect-json") && !$0.arguments.contains("--auth-check-json") } }
    func launch(arguments: [String]) throws -> any BackendRunning {
        let run = FakeRun(finishesOnCancel: finishesOnCancel)
        lock.withLock { storage.append(FakeCall(arguments: arguments, run: run)) }
        if let index = arguments.firstIndex(of: "--inspect-json") {
            let source = arguments[index + 1]
            let inspectionIndex = calls.filter { $0.arguments.contains("--inspect-json") }.count - 1
            let inspectionTitle = inspectionTitles.isEmpty ? "Example video" : inspectionTitles[min(inspectionIndex, inspectionTitles.count - 1)]
            var entries: [[String: String]] = playlist ? [["url": "https://www.youtube.com/embed/1", "title": "First", "availability": "available"], ["url": "https://www.youtube.com/embed/2", "title": "Second", "availability": "available"]] : [["url": source, "title": inspectionTitle, "availability": "available"]]
            if let inspectionStreamState { for index in entries.indices { entries[index]["streamState"] = inspectionStreamState } }
            if let embedRefererOrigin { for index in entries.indices { entries[index]["embedRefererOrigin"] = embedRefererOrigin } }
            let needsAuth = requiresAuthentication && (!acceptsSnapshot || !arguments.contains("--cookies-file"))
            var object: [String: Any] = needsAuth ? ["ok": false, "source": source, "errorCode": "authenticationRequired", "error": "Login required", "entries": []] : ["ok": true, "source": source, "title": inspectionTitle, "isPlaylist": playlist, "entries": entries]
            if inspectionCookieFallback {
                object["warnings"] = [["code": "browserCookieAccessDenied", "browser": "safari", "fallback": "withoutCookies"]]
                object["cookieFallbackUsed"] = true
            }
            run.emit(String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self))
            if inspectionAutomaticallyFinishes { run.finish(inspectionExitCode) }
        } else if let index = arguments.firstIndex(of: "--session-dir") {
            var object: [String: Any] = ["ok": ["ready", "anonymous"].contains(authStatus), "status": authStatus]
            if let authMessage { object["message"] = authMessage }
            if authStatus == "ready" {
                let path = URL(fileURLWithPath: arguments[index + 1]).appendingPathComponent("cookies.txt")
                try "# Netscape HTTP Cookie File\n".write(to: path, atomically: true, encoding: .utf8)
                object["cookieFile"] = path.path
            }
            run.emit(String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self))
            if authAutomaticallyFinishes { run.finish(0) }
        }
        return run
    }
}
private final class FakeRun: BackendRunning, @unchecked Sendable {
    let events: AsyncStream<BackendOutput>
    private let continuation: AsyncStream<BackendOutput>.Continuation
    private let lock = NSLock()
    private var cancelled = false
    private var sent: [String] = []
    private let finishesOnCancel: Bool
    var wasCancelled: Bool { lock.withLock { cancelled } }
    var inputs: [String] { lock.withLock { sent } }
    init(finishesOnCancel: Bool = true) { let stream = AsyncStream<BackendOutput>.makeStream(); events = stream.stream; continuation = stream.continuation; self.finishesOnCancel = finishesOnCancel }
    func emit(_ text: String) { continuation.yield(.line(text)) }
    func finish(_ code: Int32) { continuation.yield(.exited(code)); continuation.finish() }
    func send(_ text: String) { lock.withLock { sent.append(text) } }
    func cancel() { lock.withLock { cancelled = true }; if finishesOnCancel { finish(143) } }
}
