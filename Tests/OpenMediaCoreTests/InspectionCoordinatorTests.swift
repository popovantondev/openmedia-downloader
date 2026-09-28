import Foundation
import Testing
@testable import OpenMediaCore

struct InspectionCoordinatorTests {
    @MainActor
    @Test func thousandPlaylistRowsAcceptIncrementalMetadataUpdates() async throws {
        let backend = InspectionEventBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        let source = "https://example.org/synthetic-large-list"
        coordinator.updateInput(source)
        for _ in 0..<200 where backend.run == nil { try? await Task.sleep(nanoseconds: 5_000_000) }
        let run = try #require(backend.run)
        let base = "\"requestId\":\"\(run.requestId)\",\"generation\":\(run.generation),\"source\":\"\(source)\""
        let startedAt = Date()
        run.emit("OMD_EVENT:{\"type\":\"title\",\(base),\"title\":\"Synthetic 1000-item list\"}")
        for _ in 0..<1_000 where coordinator.rows.first?.title != "Synthetic 1000-item list" {
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        #expect(coordinator.rows.first?.title == "Synthetic 1000-item list")
        let firstTitleLatency = Date().timeIntervalSince(startedAt)
        let firstRowURL = "https://example.org/video/0"
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"synthetic-0\",\"index\":0,\"playlistPosition\":0,\"url\":\"\(firstRowURL)\",\"title\":\"Video 0\",\"availability\":\"unknown\"}")
        for _ in 0..<1_000 where coordinator.playlistGroups.first?.entries.isEmpty != false {
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        #expect(coordinator.playlistGroups.first?.entries.count == 1)
        let firstRowLatency = Date().timeIntervalSince(startedAt)

        for index in 1..<1_000 {
            let url = "https://example.org/video/\(index)"
            let itemID = "synthetic-\(index)"
            run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"\(itemID)\",\"index\":\(index),\"playlistPosition\":\(index),\"url\":\"\(url)\",\"title\":\"Video \(index)\",\"availability\":\"unknown\"}")
        }
        for index in 0..<1_000 {
            let url = "https://example.org/video/\(index)"
            let itemID = "synthetic-\(index)"
            let entry = "{\"url\":\"\(url)\",\"title\":\"Verified \(index)\",\"availability\":\"available\",\"estimates\":[]}"
            run.emit("OMD_EVENT:{\"type\":\"metadata\",\(base),\"itemId\":\"\(itemID)\",\"index\":\(index),\"playlistPosition\":\(index),\"entry\":\(entry)}")
        }
        run.emit("OMD_EVENT:{\"type\":\"inspectionComplete\",\(base),\"ok\":true,\"isPlaylist\":true,\"count\":1000}")
        run.finish()
        for _ in 0..<1_000 where coordinator.isInspecting { try? await Task.sleep(nanoseconds: 1_000_000) }

        let entries = try #require(coordinator.playlistGroups.first?.entries)
        #expect(entries.count == 1_000)
        #expect(entries[0].title == "Verified 0")
        #expect(entries[999].title == "Verified 999")
        #expect(entries.allSatisfy { $0.availability == .available })
        if ProcessInfo.processInfo.environment["OMD_BENCHMARK"] == "1" {
            print("Synthetic first title: \(String(format: "%.3f", firstTitleLatency)) s; first playlist row: \(String(format: "%.3f", firstRowLatency)) s; 1000 rows + 1000 metadata updates: \(String(format: "%.3f", Date().timeIntervalSince(startedAt))) s")
        }
    }

    @MainActor
    @Test func unknownStableItemErrorDoesNotFallBackToMisleadingIndex() async throws {
        let backend = InspectionEventBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        coordinator.updateInput("https://example.org/list")
        for _ in 0..<200 where backend.run == nil { try? await Task.sleep(nanoseconds: 5_000_000) }
        let run = try #require(backend.run)
        let base = "\"requestId\":\"\(run.requestId)\",\"generation\":\(run.generation),\"source\":\"https://example.org/list\""
        run.emit("OMD_EVENT:{\"type\":\"title\",\(base),\"title\":\"List\"}")
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"known\",\"index\":0,\"playlistPosition\":0,\"url\":\"https://example.org/video/0\",\"title\":\"First\",\"availability\":\"unknown\"}")
        run.emit("OMD_EVENT:{\"type\":\"inspectionError\",\(base),\"itemId\":\"unmapped\",\"index\":0,\"error\":\"wrong item\"}")
        run.emit("OMD_EVENT:{\"type\":\"inspectionComplete\",\(base),\"ok\":true,\"isPlaylist\":true,\"count\":1}")
        run.finish()
        for _ in 0..<200 where coordinator.isInspecting { try? await Task.sleep(nanoseconds: 5_000_000) }
        let row = try #require(coordinator.playlistGroups.first?.entries.first)
        #expect(row.url == "https://example.org/video/0")
        #expect(row.availability == .unknown)
        #expect(row.error == nil)
    }

    @MainActor
    @Test func playlistSelectionPrioritizesUnknownAndOnlyQueuesVerifiedVariants() async throws {
        let backend = InspectionEventBackend()
        let coordinator = DownloadCoordinator(client: backend, debounceNanoseconds: 1_000_000)
        coordinator.updateInput("https://example.org/list")
        for _ in 0..<200 where backend.run == nil { try? await Task.sleep(nanoseconds: 5_000_000) }
        let run = try #require(backend.run)
        let source = "https://example.org/list"
        let base = "\"requestId\":\"\(run.requestId)\",\"generation\":\(run.generation),\"source\":\"\(source)\""
        run.emit("OMD_EVENT:{\"type\":\"title\",\(base),\"title\":\"List\"}")
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"stable-a\",\"index\":0,\"url\":\"https://example.org/a\",\"title\":\"A\",\"availability\":\"unknown\"}")
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"stable-b\",\"index\":1,\"url\":\"https://example.org/b\",\"title\":\"B\",\"availability\":\"available\"}")
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"stable-c\",\"index\":2,\"url\":\"https://example.org/c\",\"title\":\"C\",\"availability\":\"unavailable\"}")
        run.emit("OMD_EVENT:{\"type\":\"playlistEntry\",\(base),\"itemId\":\"stable-d\",\"index\":3,\"url\":\"https://example.org/d\",\"title\":\"D\",\"availability\":\"authenticationRequired\"}")
        for _ in 0..<200 where coordinator.playlistGroups.first?.entries.count != 4 { try? await Task.sleep(nanoseconds: 5_000_000) }
        let group = try #require(coordinator.playlistGroups.first)
        coordinator.prioritizePlaylistEntry(groupID: group.id, entryID: "https://example.org/a")
        coordinator.prioritizePlaylistEntry(groupID: group.id, entryID: "https://example.org/a")
        coordinator.prioritizePlaylistEntry(groupID: group.id, entryID: "https://example.org/b")
        coordinator.prioritizePlaylistEntry(groupID: group.id, entryID: "https://example.org/c")
        #expect(run.sentValues.count == 1)
        let command = try #require(run.sentValues.first)
        #expect(command.hasSuffix("\n"))
        let decoded = try #require(try JSONSerialization.jsonObject(with: Data(command.dropLast().utf8)) as? [String: String])
        #expect(decoded == ["type": "prioritize", "itemId": "stable-a"])

        coordinator.addPlaylistSelection(groupID: group.id, variants: [PlaylistSelection(entryID: "https://example.org/a")])
        #expect(coordinator.rows.count == 1)
        #expect(coordinator.rows.first?.stage == .inspecting)
        #expect(coordinator.playlistGroups.contains(where: { $0.id == group.id }))
        run.emit("OMD_EVENT:{\"type\":\"metadata\",\(base),\"itemId\":\"stable-a\",\"index\":0,\"entry\":{\"url\":\"https://example.org/a\",\"title\":\"A verified\",\"availability\":\"available\",\"availableHeights\":[720],\"estimates\":[]}}")
        for _ in 0..<200 where coordinator.playlistGroups.first?.entries.first?.availability != .available { try? await Task.sleep(nanoseconds: 5_000_000) }
        #expect(coordinator.playlistGroups.first?.entries.first?.title == "A verified")
        run.emit("OMD_EVENT:{\"type\":\"inspectionComplete\",\(base),\"ok\":true,\"isPlaylist\":true,\"count\":4}")
        for _ in 0..<200 where !coordinator.rows.isEmpty { try? await Task.sleep(nanoseconds: 5_000_000) }
        #expect(coordinator.rows.isEmpty)
        coordinator.addPlaylistSelection(groupID: group.id, variants: [
            PlaylistSelection(entryID: "https://example.org/a", media: .video, quality: "720", mode: .chunks),
            PlaylistSelection(entryID: "https://example.org/a", media: .aac, quality: "best", mode: .direct),
            PlaylistSelection(entryID: "https://example.org/d", media: .aac)
        ])
        #expect(coordinator.rows.count == 3)
        #expect(coordinator.rows.map(\.media) == [.video, .aac, .aac])
        #expect(coordinator.rows.map(\.mode) == [.chunks, .direct, .auto])
        #expect(coordinator.rows.map(\.quality) == ["720", "best", "best"])
        #expect(coordinator.rows.map(\.stage) == [.queued, .queued, .authenticationRequired])
        #expect(coordinator.playlistGroups.isEmpty)
        run.finish()
    }

    @Test func sharedProgressiveFixtureDecodesStableAndLegacyIdentities() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let fixture = root.appendingPathComponent("backend/tests/fixtures/protocol/progressive-events.jsonl")
        let lines = try String(contentsOf: fixture, encoding: .utf8).split(whereSeparator: \.isNewline)
        #expect(lines.count == 8)
        var events: [BackendEvent] = []
        for line in lines {
            let data = Data(line.utf8)
            #expect((try JSONSerialization.jsonObject(with: data)) is [String: Any])
            let decoded = try JSONDecoder().decode(BackendEvent.self, from: data)
            events.append(decoded)
        }
        let byType = Dictionary(uniqueKeysWithValues: events.map { ($0.type, $0) })
        for type in ["title", "playlistEntry", "metadata", "inspectionError", "authWarning", "inspectionComplete"] {
            let event = try #require(byType[type])
            #expect(event.requestId == "r-1")
            #expect(event.generation == 3)
            #expect(event.source == "https://example.invalid/list")
        }
        #expect(byType["playlistEntry"]?.itemId == "item-a")
        #expect(byType["playlistEntry"]?.playlistPosition == 0)
        #expect(byType["metadata"]?.itemId == "item-a")
        #expect(byType["progress"]?.taskId == "task-a")
        #expect(byType["recordingFinalized"]?.taskId == "task-r")
        #expect(byType["inspectionError"]?.index == 1)
        #expect(byType["inspectionError"]?.itemId == nil)

        let futureData = Data(#"{"type":"playlistEntry","requestId":"r","generation":1,"source":"https://example.invalid","itemId":"x","playlistPosition":4,"futureOptionalField":{"ok":true}}"#.utf8)
        #expect(try JSONDecoder().decode(BackendEvent.self, from: futureData).itemId == "x")
        #expect(BackendEvent.parse(#"OMD_EVENT:{"type":"playlistEntry","requestId":"r","generation":1,"source":"https://example.invalid","index":4}"#)?.index == 4)
        #expect(BackendEvent.parse("OMD_EVENT:{\"type\":") == nil)
        #expect(throws: (any Error).self) { try JSONSerialization.jsonObject(with: Data("{\"type\":".utf8)) }
    }

    @Test func progressiveEventsRequireExactRequestGenerationAndSource() throws {
        let identity = InspectionEventIdentity(requestId: "request-a", generation: 7, source: "https://example.org/list")
        let valid = BackendEvent.parse(#"OMD_EVENT:{"type":"playlistEntry","requestId":"request-a","generation":7,"source":"https://example.org/list","index":2,"url":"https://example.org/video/2","title":"Two","availability":"unknown"}"#)!
        let staleRequest = BackendEvent.parse(#"OMD_EVENT:{"type":"metadata","requestId":"request-old","generation":7,"source":"https://example.org/list","index":2,"entry":{"url":"https://example.org/video/2","title":"Two","availability":"available","estimates":[]}}"#)!
        let staleGeneration = BackendEvent.parse(#"OMD_EVENT:{"type":"inspectionComplete","requestId":"request-a","generation":6,"source":"https://example.org/list","ok":true}"#)!
        let wrongSource = BackendEvent.parse(#"OMD_EVENT:{"type":"inspectionError","requestId":"request-a","generation":7,"source":"https://example.org/other","index":2,"error":"unavailable"}"#)!

        #expect(identity.accepts(valid))
        #expect(!identity.accepts(staleRequest))
        #expect(!identity.accepts(staleGeneration))
        #expect(!identity.accepts(wrongSource))
        #expect(valid.availability == .unknown)
    }

    @Test func lateMetadataAfterCancellationCannotBeAssociatedWithNewGeneration() throws {
        let removed = InspectionEventIdentity(requestId: "request-a", generation: 11, source: "https://example.org/list")
        let replacement = InspectionEventIdentity(requestId: "request-b", generation: 12, source: "https://example.org/list")
        let event = BackendEvent.parse(#"OMD_EVENT:{"type":"metadata","requestId":"request-a","generation":11,"source":"https://example.org/list","index":0,"entry":{"url":"https://example.org/video/0","title":"Old","availability":"available","estimates":[]}}"#)!

        #expect(removed.accepts(event))
        #expect(!replacement.accepts(event))
    }
}

private final class InspectionEventBackend: BackendClient, @unchecked Sendable {
    private let lock = NSLock()
    private var storedRun: InspectionEventRun?
    var run: InspectionEventRun? { lock.lock(); defer { lock.unlock() }; return storedRun }
    func launch(arguments: [String]) throws -> any BackendRunning {
        let requestIndex = arguments.firstIndex(of: "--request-id")!
        let generationIndex = arguments.firstIndex(of: "--generation")!
        let created = InspectionEventRun(requestId: arguments[requestIndex + 1], generation: Int(arguments[generationIndex + 1])!)
        lock.lock(); storedRun = created; lock.unlock()
        return created
    }
}

private final class InspectionEventRun: BackendRunning, @unchecked Sendable {
    let requestId: String
    let generation: Int
    private let continuation: AsyncStream<BackendOutput>.Continuation
    let events: AsyncStream<BackendOutput>
    private let lock = NSLock()
    private var sent: [String] = []
    var sentValues: [String] { lock.withLock { sent } }
    init(requestId: String, generation: Int) {
        self.requestId = requestId; self.generation = generation
        var saved: AsyncStream<BackendOutput>.Continuation!
        events = AsyncStream { saved = $0 }
        continuation = saved
    }
    func emit(_ line: String) { continuation.yield(.line(line)) }
    func finish() { continuation.yield(.exited(0)); continuation.finish() }
    func send(_ text: String) { lock.withLock { sent.append(text) } }
    func cancel() { finish() }
}
