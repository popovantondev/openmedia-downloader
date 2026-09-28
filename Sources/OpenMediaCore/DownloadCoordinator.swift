import Combine
import Foundation

@MainActor
public final class DownloadCoordinator: ObservableObject {
    @Published public private(set) var rows: [DownloadTask] = []
    @Published public private(set) var playlistGroups: [PlaylistGroup] = []
    @Published public var authPrompt: AuthPrompt?
    @Published public var overwritePrompt: OverwritePrompt?
    @Published public var batchSummary: BatchSummary?
    @Published public private(set) var logLines: [String] = []
    @Published public var inputText = ""
    @Published public var maxConcurrentFiles = 4
    @Published public var fragmentsPerFile = 4
    @Published public var outputDirectory: URL
    @Published public private(set) var isInspecting = false
    @Published public private(set) var isRunning = false
    @Published public private(set) var isAuthenticating = false
    @Published public private(set) var authenticationStatus = "anonymous"

    public var activeCount: Int { rows.filter { $0.stage.isActive }.count }
    public var queuedCount: Int { rows.filter { $0.stage == .queued }.count }
    public var completedCount: Int { rows.filter { $0.stage == .completed }.count }
    public var queueSize: QueueSize { QueueSize(tasks: rows.filter { $0.stage != .cancelled }) }
    public var estimatedTotalBytes: Int64 { queueSize.knownBytes }
    public var unknownEstimateCount: Int { queueSize.unknownCount }
    public var hasActiveWork: Bool { isRunning || isInspecting || isAuthenticating }
    public var hasCancellableWork: Bool { hasActiveWork || rows.contains { $0.stage == .queued } }
    public var additionalAuthDomains: [String] {
        let sources = rows.map(\.sourceURL) + playlistGroups.map(\.sourceURL)
        let mediaDomains = ["youtube.com", "google.com", "googlevideo.com", "youtube-nocookie.com", "vimeo.com"]
        return Set(sources.compactMap(Self.validSourceHostname).filter { host in
            !mediaDomains.contains(where: { host == $0 || host.hasSuffix("." + $0) })
        }).sorted()
    }

    private static func validSourceHostname(_ source: String) -> String? {
        guard let components = URLComponents(string: source),
              let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let rawHost = components.host?.lowercased() else { return nil }
        let host = rawHost.hasSuffix(".") ? String(rawHost.dropLast()) : rawHost
        guard host.contains("."), host.utf8.count <= 253,
              host.split(separator: ".", omittingEmptySubsequences: false).allSatisfy({ label in
                  !label.isEmpty && label.utf8.count <= 63 && label.first != "-" && label.last != "-" && label.utf8.allSatisfy { byte in
                      (byte >= 97 && byte <= 122) || (byte >= 48 && byte <= 57) || byte == 45
                  }
              }) else { return nil }
        return host
    }

    public static func embeddedRefererArguments(embedRefererOrigin: String?, sourceURL: String, mediaURL: String) -> [String] {
        let mediaHosts = ["youtube.com", "youtube-nocookie.com", "youtu.be", "googlevideo.com", "vimeo.com"]
        guard let originValue = embedRefererOrigin, let source = URLComponents(string: originValue), let originalSource = URLComponents(string: sourceURL), let target = URLComponents(string: mediaURL),
              let sourceScheme = source.scheme?.lowercased(), ["http", "https"].contains(sourceScheme),
              source.user == nil, source.password == nil, source.query == nil, source.fragment == nil,
              source.path.isEmpty || source.path == "/",
              let originalScheme = originalSource.scheme?.lowercased(), ["http", "https"].contains(originalScheme),
              originalSource.user == nil, originalSource.password == nil,
              target.user == nil, target.password == nil,
              let sourceHost = source.host?.lowercased(), let originalHost = originalSource.host?.lowercased(), let targetHost = target.host?.lowercased(),
              !mediaHosts.contains(where: { sourceHost == $0 || sourceHost.hasSuffix("." + $0) }),
              !mediaHosts.contains(where: { originalHost == $0 || originalHost.hasSuffix("." + $0) }),
              sourceHost != targetHost, originalHost != targetHost, ["youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com"].contains(where: { targetHost == $0 || targetHost.hasSuffix("." + $0) }),
              source.port == nil || (1...65535).contains(source.port!) else { return [] }
        var origin = URLComponents()
        origin.scheme = sourceScheme; origin.host = sourceHost; origin.port = source.port; origin.path = "/"
        guard let value = origin.string else { return [] }
        return ["--referer", value]
    }

    private let client: any BackendClient
    private let debounceNanoseconds: UInt64
    private var debounceTask: Task<Void, Never>?
    private var inspectedSources = Set<String>()
    private var pendingInspections: [(UUID, String)] = []
    private var inspections: [UUID: any BackendRunning] = [:]
    private var inspectionTasks: [UUID: Task<Void, Never>] = [:]
    private var inspectionIdentity: [UUID: InspectionEventIdentity] = [:]
    private var inspectionGeneration = 0
    private struct CachedInspection {
        let response: InspectionResponse
        let insertedAt: Date
    }
    private var inspectionCache: [String: CachedInspection] = [:]
    private let inspectionCacheLifetime: TimeInterval
    private let now: () -> Date
    private var authorizationContextID = UUID()
    private var inspectionTitles: [String: String] = [:]
    private var playlistItemURLs: [String: String] = [:]
    private var playlistItemIDsByURL: [String: String] = [:]
    private var playlistEntryIndicesBySource: [String: [String: Int]] = [:]
    private var prioritizedPlaylistItems = Set<String>()
    private var downloads: [UUID: any BackendRunning] = [:]
    private var downloadTasks: [UUID: Task<Void, Never>] = [:]
    private var waitingDownloads: [UUID] = []
    private var batchIDs = Set<UUID>()
    private var requestedCancellation = Set<UUID>()
    private var stoppedStreams = Set<UUID>()
    private var endEvents: [UUID: TaskStage] = [:]
    private var pendingOverwrites: [OverwritePrompt] = []
    private var pendingStart = false
    private var authenticationResolved = false
    private var authRun: (any BackendRunning)?
    private var authTask: Task<Void, Never>?
    private var authenticationCancellationRequested = false
    private var authenticationFailuresForSession = Set<UUID>()
    private var cookieFallbackWarningShown = false
    private var session: PrivateCookieSession?

    public init(client: any BackendClient = ProcessBackendClient(), outputDirectory: URL? = nil, debounceNanoseconds: UInt64 = 600_000_000, inspectionCacheLifetime: TimeInterval = 15 * 60, now: @escaping () -> Date = Date.init) {
        self.client = client; self.debounceNanoseconds = debounceNanoseconds
        self.inspectionCacheLifetime = max(0, inspectionCacheLifetime); self.now = now
        self.outputDirectory = outputDirectory ?? FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads")
    }

    public func updateInput(_ text: String) {
        inputText = text; debounceTask?.cancel()
        debounceTask = Task { [weak self] in
            guard let self else { return }
            do { try await Task.sleep(nanoseconds: debounceNanoseconds) } catch { return }
            inspectInput()
        }
    }

    public static func extractURLs(from text: String) -> [String] {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return [] }
        var seen = Set<String>()
        return detector.matches(in: text, range: NSRange(text.startIndex..., in: text)).compactMap {
            guard let url = $0.url, ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return nil }
            let value = url.absoluteString
            return seen.insert(value).inserted ? value : nil
        }
    }

    public func inspectInput(force: Bool = false) {
        debounceTask?.cancel()
        for source in Self.extractURLs(from: inputText) {
            if force {
                let existing = rows.filter { $0.sourceURL == source }
                let retryRows = existing.filter {
                    [.failed, .authenticationRequired, .cancelled].contains($0.stage) && inspections[$0.id] == nil && downloads[$0.id] == nil
                }
                if !retryRows.isEmpty {
                    for row in retryRows {
                        mutate(row.id) { $0.stage = .inspecting; $0.errorCode = nil; $0.errorMessage = nil }
                        pendingInspections.append((row.id, row.url))
                    }
                    continue
                }
                if !existing.isEmpty || playlistGroups.contains(where: { $0.sourceURL == source }) { continue }
            } else if inspectedSources.contains(source) { continue }
            guard !pendingInspections.contains(where: { $0.1 == source }), !rows.contains(where: { $0.sourceURL == source && $0.stage == .inspecting }) else { continue }
            inspectedSources.insert(source)
            let id = UUID()
            rows.append(DownloadTask(id: id, entry: MediaEntry(url: source, title: source), stage: .inspecting))
            pendingInspections.append((id, source))
        }
        launchInspections()
    }

    public func addVariant(for taskID: UUID) {
        guard let original = rows.first(where: { $0.id == taskID }), original.stage != .inspecting else { return }
        let entry = MediaEntry(url: original.url, title: original.title, duration: original.duration, availableHeights: original.availableHeights, estimates: original.estimates, embedRefererOrigin: original.embedRefererOrigin)
        rows.append(DownloadTask(entry: entry, sourceURL: original.sourceURL, media: original.media, quality: original.quality, mode: original.mode))
    }

    public func updateVariant(_ taskID: UUID, media: MediaKind? = nil, quality: String? = nil, mode: TransferMode? = nil) {
        guard let i = rows.firstIndex(where: { $0.id == taskID }), !rows[i].stage.isActive, rows[i].stage != .inspecting else { return }
        guard downloads[taskID] == nil, inspections[taskID] == nil else { return }
        if let media { rows[i].media = media }
        if let quality { rows[i].quality = quality }
        if !QualityOptions.values(for: rows[i].media).contains(rows[i].quality) {
            rows[i].quality = QualityOptions.values(for: rows[i].media)[0]
        }
        if let mode { rows[i].mode = mode }
        if rows[i].stage.isTerminal { rows[i].stage = .queued; rows[i].progress = DownloadProgress() }
    }

    public func applyToAll(media: MediaKind? = nil, quality: String? = nil, mode: TransferMode? = nil) {
        for id in rows.map(\.id) { updateVariant(id, media: media, quality: quality, mode: mode) }
    }

    public func addPlaylistSelection(groupID: UUID, variants: [PlaylistSelection]) {
        guard let group = playlistGroups.first(where: { $0.id == groupID }) else { return }
        let entriesByID = Dictionary(group.entries.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let selectedEntries = variants.compactMap { entriesByID[$0.entryID] }
        if let unknown = selectedEntries.first(where: { $0.availability == .unknown }) {
            prioritizePlaylistEntry(groupID: groupID, entryID: unknown.id)
            return
        }
        for variant in variants {
            guard let entry = entriesByID[variant.entryID] else { continue }
            let stage: TaskStage
            switch entry.availability {
            case .available: stage = .queued
            case .authenticationRequired: stage = .authenticationRequired
            case .unavailable: stage = .failed
            case .unknown: continue
            }
            var row = DownloadTask(entry: entry, sourceURL: group.sourceURL, media: variant.media, quality: variant.quality, mode: variant.mode, stage: stage)
            if !QualityOptions.values(for: row.media).contains(row.quality) { row.quality = QualityOptions.values(for: row.media)[0] }
            rows.append(row)
        }
        dismissPlaylist(groupID)
    }

    public func prioritizePlaylistEntry(groupID: UUID, entryID: String) {
        guard let group = playlistGroups.first(where: { $0.id == groupID }),
              let entry = group.entries.first(where: { $0.id == entryID }), entry.availability == .unknown,
              let itemId = playlistItemIDsByURL[group.sourceURL + "|" + entry.url],
              let runMatch = inspectionIdentity.first(where: { $0.value.source == group.sourceURL && inspections[$0.key] != nil }),
              let run = inspections[runMatch.key] else { return }
        let dedupeKey = runMatch.value.requestId + "|" + itemId
        guard prioritizedPlaylistItems.insert(dedupeKey).inserted else { return }
        struct PriorityCommand: Encodable { let type = "prioritize"; let itemId: String }
        guard var command = try? JSONEncoder().encode(PriorityCommand(itemId: itemId)) else { return }
        command.append(0x0A)
        run.send(String(decoding: command, as: UTF8.self))
    }

    public func dismissPlaylist(_ groupID: UUID) {
        if let source = playlistGroups.first(where: { $0.id == groupID })?.sourceURL {
            playlistEntryIndicesBySource[source] = nil
            let prefix = source + "|"
            playlistItemURLs = playlistItemURLs.filter { !$0.key.hasPrefix(prefix) }
            playlistItemIDsByURL = playlistItemIDsByURL.filter { !$0.key.hasPrefix(prefix) }
        }
        playlistGroups.removeAll { $0.id == groupID }
        resumePendingStart()
    }

    public func requestAuthentication() {
        guard !isRunning, !isAuthenticating else { return }
        authPrompt = AuthPrompt()
    }

    public func cancelAuthentication() {
        authPrompt = nil; pendingStart = false
        if let authRun {
            authenticationCancellationRequested = true
            authRun.cancel()
        }
    }

    public func resolveAuthentication(_ choice: AuthChoice, allowedDomains: [String] = []) {
        guard !isRunning, !isAuthenticating else { return }
        authorizationContextID = UUID()
        inspectionCache.removeAll()
        if choice == .anonymous {
            session = nil; authenticationFailuresForSession.removeAll()
            authPrompt = nil
            authenticationResolved = true; authenticationStatus = "anonymous"
            launchInspections()
            resumePendingStart(); return
        }
        let priorStatus = authenticationStatus
        let priorResolution = authenticationResolved
        authenticationCancellationRequested = false
        authenticationResolved = false
        if authPrompt == nil { authPrompt = AuthPrompt() }
        do {
            let relevant = Set(additionalAuthDomains)
            let approvedDomains = choice == .anonymous ? [] : Set(allowedDomains.map { $0.lowercased() }).intersection(relevant).sorted()
            let newSession = try PrivateCookieSession(authDomains: approvedDomains)
            var args = ["--auth-check-json", "--session-dir", newSession.directory.path]
            switch choice {
            case .anonymous: break
            case .browser(let browser): args += ["--cookies-browser", browser, "--auth-url", "https://www.youtube.com/watch?v=jNQXAC9IVRw"]
            case .cookiesFile(let url): args += ["--cookies-file", url.path]
            }
            for domain in approvedDomains { args += ["--auth-domain", domain] }
            let run = try client.launch(arguments: args)
            authRun = run; isAuthenticating = true; authenticationStatus = "checking"
            authTask = Task { [weak self] in
                let response = await Self.collectJSON(from: run, type: AuthResponse.self)
                guard let self else { return }
                self.authRun = nil; self.authTask = nil; self.isAuthenticating = false
                if self.authenticationCancellationRequested {
                    self.authenticationCancellationRequested = false
                    self.authenticationStatus = priorStatus; self.authenticationResolved = priorResolution
                    self.launchInspections()
                    return
                }
                if let value = response.value, response.exitCode == 0, value.ok, value.status == "ready", let path = value.cookieFile, newSession.acceptCookie(path: path) {
                    self.session = newSession; self.inspectionCache.removeAll(); self.authenticationResolved = true; self.authenticationStatus = "ready"; self.authPrompt = nil
                    self.authenticationFailuresForSession.removeAll()
                    self.cookieFallbackWarningShown = false
                    self.recheckAuthenticationRequiredRows()
                    self.launchInspections()
                    self.resumePendingStart()
                } else if let value = response.value, response.exitCode == 0, value.ok, value.status == "anonymous" {
                    self.session = nil; self.inspectionCache.removeAll(); self.authenticationFailuresForSession.removeAll()
                    self.authenticationResolved = true; self.authenticationStatus = "anonymous"; self.authPrompt = nil
                    self.appendLog("authenticationAnonymous")
                    self.launchInspections()
                    self.resumePendingStart()
                } else {
                    let reported = response.value?.status
                    let code = reported == "ready" || reported == "anonymous" ? "authenticationCheckFailed" : reported ?? "authenticationCheckFailed"
                    self.authenticationResolved = false; self.authenticationStatus = code
                    self.authPrompt = AuthPrompt(errorCode: code, message: Self.sanitize(response.value?.detail ?? code))
                    self.launchInspections()
                }
            }
        } catch {
            authenticationStatus = "authenticationCheckFailed"
            authPrompt = AuthPrompt(errorCode: authenticationStatus, message: Self.sanitize(error.localizedDescription))
            launchInspections()
        }
    }

    public func startDownloads() {
        guard !isRunning else { return }
        inspectInput()
        pendingStart = true; resumePendingStart()
    }

    public func answerOverwrite(_ overwrite: Bool) {
        guard let prompt = overwritePrompt else { return }
        answerOverwrite(taskID: prompt.taskID, overwrite: overwrite)
    }

    public func answerOverwrite(taskID: UUID, overwrite: Bool) {
        downloads[taskID]?.send(overwrite ? "y\n" : "n\n")
        pendingOverwrites.removeAll { $0.taskID == taskID }
        if overwritePrompt?.taskID == taskID { overwritePrompt = nil }
        mutate(taskID) { if $0.stage == .waitingForOverwrite { $0.stage = .preparing } }
        showNextOverwrite()
    }

    public func stopAndSave(_ taskID: UUID) {
        guard let row = rows.first(where: { $0.id == taskID }), row.streamState == .live,
              let run = downloads[taskID], !stoppedStreams.contains(taskID) else { return }
        stoppedStreams.insert(taskID)
        mutate(taskID) { $0.stage = .finalizing }
        appendLog("recordingStopRequested: \(row.title)")
        run.send("stop\n")
    }

    public func removeOrCancel(_ taskID: UUID) {
        if let run = downloads[taskID] {
            if rows.first(where: { $0.id == taskID })?.streamState == .live { stopAndSave(taskID); return }
            requestedCancellation.insert(taskID); run.cancel()
            discardOverwrite(taskID); return
        }
        if let run = inspections[taskID] {
            requestedCancellation.insert(taskID); run.cancel()
            mutate(taskID) { $0.stage = .cancelled }; return
        }
        pendingInspections.removeAll { $0.0 == taskID }
        waitingDownloads.removeAll { $0 == taskID }
        if isRunning && batchIDs.contains(taskID) { mutate(taskID) { $0.stage = .cancelled } }
        else { rows.removeAll { $0.id == taskID } }
        launchInspections(); finishBatchIfReady()
    }

    public func cancelAll() {
        debounceTask?.cancel(); pendingStart = false
        for (id, run) in inspections { requestedCancellation.insert(id); run.cancel(); mutate(id) { $0.stage = .cancelled } }
        for (id, _) in pendingInspections { mutate(id) { $0.stage = .cancelled } }
        pendingInspections.removeAll()
        for (id, run) in downloads {
            if rows.first(where: { $0.id == id })?.streamState == .live { stopAndSave(id) }
            else { requestedCancellation.insert(id); run.cancel() }
        }
        for id in waitingDownloads { mutate(id) { $0.stage = .cancelled } }
        for id in rows.filter({ $0.stage == .queued }).map(\.id) { mutate(id) { $0.stage = .cancelled } }
        waitingDownloads.removeAll(); pendingOverwrites.removeAll(); overwritePrompt = nil
        cancelAuthentication(); launchInspections(); finishBatchIfReady()
    }

    /// Force active backend process groups to stop; recording recovery folders are retained.
    public func forceStopAll() {
        debounceTask?.cancel(); pendingStart = false
        for (id, run) in inspections {
            requestedCancellation.insert(id); run.cancel(); mutate(id) { $0.stage = .cancelled }
        }
        for (id, _) in pendingInspections { mutate(id) { $0.stage = .cancelled } }
        pendingInspections.removeAll()
        for (id, run) in downloads { requestedCancellation.insert(id); run.cancel() }
        for id in waitingDownloads { mutate(id) { $0.stage = .cancelled } }
        for id in rows.filter({ $0.stage == .queued }).map(\.id) { mutate(id) { $0.stage = .cancelled } }
        waitingDownloads.removeAll(); pendingOverwrites.removeAll(); overwritePrompt = nil
        cancelAuthentication(); session = nil
        finishBatchIfReady()
    }

    public func clearFinished() {
        rows.removeAll { $0.stage.isTerminal && downloads[$0.id] == nil && inspections[$0.id] == nil }
    }

    public func retry(_ taskID: UUID) {
        guard downloads[taskID] == nil, inspections[taskID] == nil else { return }
        if rows.first(where: { $0.id == taskID })?.streamState == .endedProcessing {
            mutate(taskID) { $0.stage = .inspecting; $0.errorCode = nil; $0.errorMessage = nil }
            if let url = rows.first(where: { $0.id == taskID })?.url { pendingInspections.append((taskID, url)); launchInspections() }
            return
        }
        authenticationFailuresForSession.remove(taskID)
        mutate(taskID) { $0.stage = .queued; $0.errorCode = nil; $0.errorMessage = nil; $0.progress = DownloadProgress() }
    }

    @discardableResult
    public func chooseStreamStart(_ start: String, for taskID: UUID) -> Bool {
        guard start == "now" || start == "from-start",
              let row = rows.first(where: { $0.id == taskID }), row.streamState == .live else { return false }
        guard start != "from-start" || row.fromStartSupported else {
            mutate(taskID) { $0.errorCode = "fromStartUnavailable"; $0.errorMessage = row.fromStartReason ?? "archiveUnavailable" }
            return false
        }
        mutate(taskID) { $0.streamStart = start; $0.errorCode = nil; $0.errorMessage = nil }
        return true
    }

    public func shutdown() { cancelAll(); session = nil }

    private func launchInspections() {
        while !isAuthenticating && inspections.count < 4 && !pendingInspections.isEmpty {
            let (id, source) = pendingInspections.removeFirst()
            guard rows.contains(where: { $0.id == id }) else { continue }
            let contextID = authorizationContextID
            let cacheKey = "\(contextID.uuidString)|\(source)"
            if let cached = inspectionCache[cacheKey] {
                if now().timeIntervalSince(cached.insertedAt) < inspectionCacheLifetime {
                    applyInspection(cached.response, source: source, rowID: id, exitCode: 0)
                    continue
                }
                inspectionCache[cacheKey] = nil
            }
            if contextID != authorizationContextID {
                continue
            }
            do {
                let cookieLease = session
                inspectionGeneration += 1
                let request = UUID().uuidString
                let generation = inspectionGeneration
                inspectionIdentity[id] = InspectionEventIdentity(requestId: request, generation: generation, source: source)
                let run = try client.launch(arguments: ["--inspect-json", source, "--inspect-stream", "--request-id", request, "--generation", String(generation)] + cookieArguments)
                inspections[id] = run
                inspectionTasks[id] = Task { [weak self] in
                    var exitCode: Int32?; var fallback: InspectionResponse?
                    var streamedEntries: [Int: MediaEntry] = [:]
                    var streamedTitle: String?
                    var streamedPlaylist: Bool?
                    var streamCompleted = false
                    for await output in run.events {
                        guard let self else { break }
                        switch output {
                        case .line(let line):
                            if let event = BackendEvent.parse(line), self.isCurrent(event, id: id) {
                                self.consumeInspectionEvent(event, rowID: id, source: source)
                                if event.type == "title" { streamedTitle = event.title }
                                if event.type == "metadata", let entry = event.entry {
                                    let index = event.playlistPosition ?? event.index ?? streamedEntries.count
                                    streamedEntries[index] = entry
                                }
                                if event.type == "playlistEntry", let url = event.url {
                                    let index = event.playlistPosition ?? event.index ?? streamedEntries.count
                                    if let itemId = event.itemId {
                                        self.playlistItemURLs[source + "|" + itemId] = url
                                        self.playlistItemIDsByURL[source + "|" + url] = itemId
                                    }
                                    streamedEntries[index] = MediaEntry(url: url, title: event.title ?? url, availability: event.availability ?? .unknown)
                                }
                                if event.type == "inspectionComplete" { streamedPlaylist = event.isPlaylist; streamCompleted = event.ok == true }
                            }
                            if let data = line.data(using: .utf8), let response = try? JSONDecoder().decode(InspectionResponse.self, from: data) { fallback = response }
                        case .exited(let code): exitCode = code
                        }
                    }
                    withExtendedLifetime(cookieLease) {}
                    guard let self else { return }
                    self.inspections[id] = nil; self.inspectionTasks[id] = nil
                    let identity = self.inspectionIdentity.removeValue(forKey: id)
                    if let identity { self.prioritizedPlaylistItems = self.prioritizedPlaylistItems.filter { !$0.hasPrefix(identity.requestId + "|") } }
                    if self.requestedCancellation.remove(id) != nil { self.mutate(id) { $0.stage = .cancelled } }
                    else {
                        let isCurrentContext = contextID == self.authorizationContextID
                        if !isCurrentContext, self.rows.contains(where: { $0.id == id }) {
                            self.mutate(id) { $0.stage = .inspecting }
                            self.pendingInspections.append((id, source))
                        } else if let fallback, identity != nil {
                            self.applyInspection(fallback, source: source, rowID: id, exitCode: exitCode)
                            if isCurrentContext, exitCode == 0, fallback.ok {
                                self.inspectionCache[cacheKey] = CachedInspection(response: fallback, insertedAt: self.now())
                            }
                        } else if streamCompleted, identity != nil {
                            let entries = streamedEntries.keys.sorted().compactMap { streamedEntries[$0] }
                            if isCurrentContext, exitCode == 0 {
                                let response = InspectionResponse(ok: true, source: source, title: streamedTitle, isPlaylist: streamedPlaylist, entries: entries)
                                self.inspectionCache[cacheKey] = CachedInspection(response: response, insertedAt: self.now())
                            }
                        } else if self.rows.contains(where: { $0.id == id }), self.rows.first(where: { $0.id == id })?.stage == .inspecting {
                            self.mutate(id) { $0.stage = exitCode == 0 ? .queued : .failed; $0.errorCode = exitCode == 0 ? nil : "inspectionFailed" }
                        }
                        if self.rows.first(where: { $0.id == id })?.stage == .authenticationRequired {
                            if self.session != nil && cookieLease !== self.session {
                                self.mutate(id) { $0.stage = .inspecting }
                                self.pendingInspections.append((id, source))
                            } else if self.session != nil { self.authenticationFailuresForSession.insert(id) }
                        }
                    }
                    self.launchInspections(); self.resumePendingStart()
                }
            } catch {
                mutate(id) { $0.stage = .failed; $0.errorCode = "backendLaunchFailed"; $0.errorMessage = Self.sanitize(error.localizedDescription) }
                inspectionIdentity[id] = nil
            }
        }
        isInspecting = !inspections.isEmpty || !pendingInspections.isEmpty
    }

    private func isCurrent(_ event: BackendEvent, id: UUID) -> Bool {
        guard let identity = inspectionIdentity[id] else { return false }
        return identity.accepts(event) && !requestedCancellation.contains(id) && rows.contains(where: { $0.id == id && $0.stage != .cancelled })
    }

    private func consumeInspectionEvent(_ event: BackendEvent, rowID: UUID, source: String) {
        switch event.type {
        case "title":
            if let title = event.title, !title.isEmpty { mutate(rowID) { $0.title = title } }
            inspectionTitles[source] = event.title
        case "playlistEntry":
            guard let url = event.url else { return }
            ensurePlaylist(source: source, title: inspectionTitles[source] ?? source)
            if let itemId = event.itemId {
                playlistItemURLs[source + "|" + itemId] = url
                playlistItemIDsByURL[source + "|" + url] = itemId
            }
            if let groupIndex = playlistGroups.firstIndex(where: { $0.sourceURL == source }), playlistEntryIndicesBySource[source]?[url] == nil {
                let entryIndex = playlistGroups[groupIndex].entries.count
                playlistGroups[groupIndex].entries.append(MediaEntry(url: url, title: event.title ?? url, availability: event.availability ?? .unknown))
                playlistEntryIndicesBySource[source, default: [:]][url] = entryIndex
            }
        case "metadata":
            guard let entry = event.entry else { return }
            if let groupIndex = playlistGroups.firstIndex(where: { $0.sourceURL == source }) {
                let matchURL: String?
                if let itemId = event.itemId { matchURL = playlistItemURLs[source + "|" + itemId] }
                else { matchURL = entry.url }
                if let matchURL,
                   let index = playlistEntryIndex(source: source, url: matchURL, groupIndex: groupIndex) {
                    let old = playlistGroups[groupIndex].entries[index]
                    playlistGroups[groupIndex].entries[index] = MediaEntry(url: old.url, title: entry.title, duration: entry.duration, availableHeights: entry.availableHeights, availability: entry.availability, error: entry.error, estimates: entry.estimates, streamState: entry.streamState, fromStartSupported: entry.fromStartSupported, fromStartReason: entry.fromStartReason, embedRefererOrigin: entry.embedRefererOrigin ?? old.embedRefererOrigin)
                } else if event.itemId == nil, let legacy = event.index, playlistGroups[groupIndex].entries.indices.contains(legacy) { playlistGroups[groupIndex].entries[legacy] = entry }
            } else if event.index == 0, rows.contains(where: { $0.id == rowID }) {
                mutate(rowID) { $0.title = entry.title; $0.url = entry.url; $0.estimates = entry.estimates; $0.availableHeights = entry.availableHeights; $0.duration = entry.duration; $0.streamState = entry.streamState; $0.fromStartSupported = entry.fromStartSupported; $0.fromStartReason = entry.fromStartReason; $0.embedRefererOrigin = entry.embedRefererOrigin; $0.stage = entry.streamState == .scheduled ? .scheduled : entry.streamState == .endedProcessing ? .endedProcessing : .queued }
            }
        case "inspectionError":
            if let groupIndex = playlistGroups.firstIndex(where: { $0.sourceURL == source }) {
                if let itemId = event.itemId {
                    if let itemURL = playlistItemURLs[source + "|" + itemId],
                       let index = playlistEntryIndex(source: source, url: itemURL, groupIndex: groupIndex) {
                        playlistGroups[groupIndex].entries[index].availability = .unavailable
                        playlistGroups[groupIndex].entries[index].error = event.error
                    }
                } else if let index = event.index, playlistGroups[groupIndex].entries.indices.contains(index) {
                    playlistGroups[groupIndex].entries[index].availability = .unavailable
                    playlistGroups[groupIndex].entries[index].error = event.error
                }
            } else { mutate(rowID) { $0.stage = .failed; $0.errorCode = "inspectionFailed"; $0.errorMessage = Self.sanitize(event.error ?? "inspectionFailed") } }
        case "inspectionComplete":
            if event.isPlaylist == true { rows.removeAll { $0.id == rowID } }
            else if event.ok == true { mutate(rowID) { if $0.stage == .inspecting { $0.stage = .queued } } }
        default: break
        }
    }

    private func ensurePlaylist(source: String, title: String) {
        if let groupIndex = playlistGroups.firstIndex(where: { $0.sourceURL == source }) {
            if playlistEntryIndicesBySource[source] == nil {
                var indices: [String: Int] = [:]
                for (index, entry) in playlistGroups[groupIndex].entries.enumerated() where indices[entry.url] == nil {
                    indices[entry.url] = index
                }
                playlistEntryIndicesBySource[source] = indices
            }
            return
        }
        playlistGroups.append(PlaylistGroup(sourceURL: source, title: title.isEmpty ? source : title, entries: []))
        playlistEntryIndicesBySource[source] = [:]
    }

    private func playlistEntryIndex(source: String, url: String, groupIndex: Int) -> Int? {
        if let index = playlistEntryIndicesBySource[source]?[url] {
            return index
        }
        // Alte Prüfereignisse können playlistEntry auslassen. Suche dann einmal und merke den Index.
        guard let index = playlistGroups[groupIndex].entries.firstIndex(where: { $0.url == url }) else { return nil }
        playlistEntryIndicesBySource[source, default: [:]][url] = index
        return index
    }

    private func applyInspection(_ result: InspectionResponse?, source: String, rowID: UUID, exitCode: Int32?) {
        guard let result else {
            mutate(rowID) { $0.stage = .failed; $0.errorCode = "invalidBackendResponse"; $0.errorMessage = "invalidBackendResponse" }; return
        }
        if result.cookieFallbackUsed == true || result.warnings?.contains(where: {
            $0.code == "browserCookieAccessDenied" && $0.fallback == "withoutCookies"
        }) == true { reportCookieFallback() }
        guard exitCode == 0 || !result.ok else {
            mutate(rowID) { $0.stage = .failed; $0.errorCode = "inspectionFailed"; $0.errorMessage = "inspectionFailed" }
            return
        }
        let entries = result.entries ?? []
        if result.isPlaylist == true && !entries.isEmpty {
            rows.removeAll { $0.id == rowID }
            playlistGroups.append(PlaylistGroup(sourceURL: source, title: result.title ?? source, entries: entries))
            var indices: [String: Int] = [:]
            for (index, entry) in entries.enumerated() where indices[entry.url] == nil { indices[entry.url] = index }
            playlistEntryIndicesBySource[source] = indices
            appendLog("playlistReady: \(result.title ?? source) (\(entries.count))"); return
        }
        if let entry = entries.first {
            let stage: TaskStage = entry.availability == .authenticationRequired ? .authenticationRequired : entry.availability == .unavailable ? .failed : result.ok ? .queued : .failed
            if let index = rows.firstIndex(where: { $0.id == rowID }) {
                let previous = rows[index]
                let streamStage: TaskStage = entry.streamState == .scheduled ? .scheduled : entry.streamState == .endedProcessing ? .endedProcessing : stage
                rows[index] = DownloadTask(id: rowID, entry: entry, sourceURL: previous.sourceURL, media: previous.media, quality: previous.quality, mode: previous.mode, stage: streamStage)
                rows[index].errorCode = result.errorCode
                appendLog("\(stage.rawValue): \(entry.title)")
            }
        } else {
            mutate(rowID) {
                $0.stage = result.errorCode == "authenticationRequired" ? .authenticationRequired : .failed
                $0.errorCode = result.errorCode ?? "inspectionFailed"
                $0.errorMessage = Self.sanitize(result.error ?? "inspectionFailed")
            }
            appendLog("\(result.errorCode ?? "inspectionFailed"): \(source)")
        }
    }

    private func resumePendingStart() {
        guard pendingStart, !isRunning, !isInspecting, playlistGroups.isEmpty, !isAuthenticating else { return }
        guard authenticationResolved else { if authPrompt == nil { authPrompt = AuthPrompt() }; return }
        pendingStart = false; batchSummary = nil
        var seen = Set<String>()
        var duplicates = Set<UUID>()
        let authUnavailable = rows.filter { $0.stage == .authenticationRequired && (session == nil || authenticationFailuresForSession.contains($0.id)) }
        let candidates = rows.filter { row in
            [.queued, .failed].contains(row.stage) || (row.stage == .authenticationRequired && session != nil && !authenticationFailuresForSession.contains(row.id))
        }
        for row in candidates where !seen.insert(row.variantKey).inserted { duplicates.insert(row.id) }
        rows.removeAll { duplicates.contains($0.id) }
        if !duplicates.isEmpty { appendLog("duplicateVariantsSkipped: \(duplicates.count)") }
        waitingDownloads = candidates.filter { !duplicates.contains($0.id) }.map(\.id)
        guard !waitingDownloads.isEmpty else {
            if !authUnavailable.isEmpty { batchSummary = BatchSummary(tasks: authUnavailable) }
            return
        }
        batchIDs = Set(waitingDownloads + authUnavailable.map(\.id)); requestedCancellation.subtract(batchIDs); endEvents.removeAll()
        for id in waitingDownloads { mutate(id) { $0.stage = .queued; $0.progress = DownloadProgress(); $0.errorCode = nil; $0.errorMessage = nil } }
        isRunning = true; launchDownloads()
    }

    private func launchDownloads() {
        let limit = max(1, min(16, maxConcurrentFiles))
        while downloads.count < limit && !waitingDownloads.isEmpty {
            let id = waitingDownloads.removeFirst()
            guard let row = rows.first(where: { $0.id == id }) else { continue }
            mutate(id) { $0.stage = .preparing }
            let args: [String]
            let refererArguments = Self.embeddedRefererArguments(embedRefererOrigin: row.embedRefererOrigin, sourceURL: row.sourceURL, mediaURL: row.url)
            if row.streamState == .live {
                args = ["--record-stream", "--task-id", row.id.uuidString, "--stream-start", row.streamStart, "-o", outputDirectory.path, "-q", row.quality, "--media", row.media.rawValue, "--workers", String(max(1, min(32, fragmentsPerFile)))] + (row.streamStart == "from-start" && row.fromStartSupported ? ["--from-start-supported"] : []) + refererArguments + cookieArguments + [row.url]
            } else {
                args = ["-o", outputDirectory.path, "-q", row.quality, "--media", row.media.rawValue, "--mode", row.mode.rawValue, "--workers", String(max(1, min(32, fragmentsPerFile))), "--ask-overwrite"] + refererArguments + cookieArguments + [row.url]
            }
            do {
                let cookieLease = session
                let run = try client.launch(arguments: args)
                downloads[id] = run
                downloadTasks[id] = Task { [weak self] in
                    var status: Int32?
                    for await output in run.events {
                        guard let self else { break }
                        switch output {
                        case .line(let line): self.consumeDownloadLine(line, taskID: id)
                        case .exited(let code): status = code
                        }
                    }
                    withExtendedLifetime(cookieLease) {}
                    guard let self else { return }
                    self.downloadFinished(id, status: status)
                }
            } catch {
                mutate(id) { $0.stage = .failed; $0.errorCode = "backendLaunchFailed"; $0.errorMessage = Self.sanitize(error.localizedDescription) }
            }
        }
        finishBatchIfReady()
    }

    private func recheckAuthenticationRequiredRows() {
        for row in rows where row.stage == .authenticationRequired && inspections[row.id] == nil {
            mutate(row.id) { $0.stage = .inspecting; $0.errorMessage = nil; $0.errorCode = nil }
            pendingInspections.append((row.id, row.url))
        }
        launchInspections()
    }

    private func consumeDownloadLine(_ line: String, taskID: UUID) {
        guard !requestedCancellation.contains(taskID), let row = rows.first(where: { $0.id == taskID }), !row.stage.isTerminal else { return }
        guard let event = BackendEvent.parse(line) else { appendLog(Self.sanitize(line)); return }
        if event.code == "browserCookieAccessDenied", event.fallback == "withoutCookies" { reportCookieFallback() }
        if event.code == "publicAccessFallback", event.fallback == "withoutCookies" {
            mutate(taskID) { $0.progress = DownloadProgress() }
            appendLog("publicAccessFallback")
        }
        switch event.type {
        case "stage":
            if let raw = event.stage, let stage = TaskStage(rawValue: raw), [.preparing, .live, .finalizing, .downloading, .merging].contains(stage) { mutate(taskID) { if $0.stage != .finalizing || stage == .finalizing { $0.stage = stage } } }
        case "progress":
            mutate(taskID) {
                if $0.stage != .finalizing {
                    if $0.streamState == .live { $0.stage = .live }
                    else if $0.stage != .merging && $0.stage != .waitingForOverwrite { $0.stage = .downloading }
                }
                if $0.streamState != .live, let value = event.progress, value.isFinite { $0.progress.fraction = max(0, min(1, value)) }
                if let value = event.downloadedBytes, value >= 0 { $0.progress.downloadedBytes = value }
                if $0.streamState != .live, let value = event.totalBytes, value > 0 { $0.progress.totalBytes = value }
                if let value = event.elapsedSeconds, value.isFinite, value >= 0 { $0.progress.elapsedSeconds = value }
                if let value = event.speedBytesPerSecond, value.isFinite, value >= 0 { $0.progress.speedBytesPerSecond = value }
                if let value = event.etaSeconds, value.isFinite, value >= 0 { $0.progress.etaSeconds = value }
                if let value = event.fragmentIndex { $0.progress.fragmentIndex = value }
                if let value = event.fragmentCount { $0.progress.fragmentCount = value }
            }
        case "file": mutate(taskID) {
            $0.outputPath = event.path
            if let path = event.path { $0.title = URL(fileURLWithPath: path).lastPathComponent }
        }
        case "overwrite":
            if let path = event.path, !pendingOverwrites.contains(where: { $0.taskID == taskID }), overwritePrompt?.taskID != taskID {
                pendingOverwrites.append(OverwritePrompt(taskID: taskID, path: path))
                mutate(taskID) { $0.stage = .waitingForOverwrite }; showNextOverwrite()
            }
        case "completed", "skipped":
            if endEvents[taskID] != .failed && endEvents[taskID] != .authenticationRequired {
                endEvents[taskID] = event.type == "completed" ? .completed : .skipped
            }
            mutate(taskID) { if let path = event.path { $0.outputPath = path } }
        case "error":
            endEvents[taskID] = event.code == "authenticationRequired" ? .authenticationRequired : .failed
            mutate(taskID) { $0.errorCode = event.code; $0.errorMessage = Self.sanitize(event.message ?? event.code ?? "downloadFailed") }
        default: break
        }
    }

    private func downloadFinished(_ id: UUID, status: Int32?) {
        downloads[id] = nil; downloadTasks[id] = nil; discardOverwrite(id)
        let wasStoppedStream = stoppedStreams.remove(id) != nil
        let terminal: TaskStage
        if requestedCancellation.remove(id) != nil { terminal = .cancelled }
        else if let end = endEvents[id], end == .authenticationRequired || end == .failed { terminal = end }
        else if status == 0 { terminal = endEvents[id] ?? .completed }
        else if wasStoppedStream && status == 130 { terminal = .failed }
        else { terminal = .failed }
        mutate(id) {
            $0.stage = terminal
            if terminal == .completed { $0.progress.fraction = 1 }
            if terminal == .failed && $0.errorCode == nil { $0.errorCode = "downloadFailed"; $0.errorMessage = "downloadFailed" }
        }
        if let row = rows.first(where: { $0.id == id }) { appendLog("\(terminal.rawValue): \(row.title)") }
        endEvents[id] = nil; launchDownloads()
    }

    private func finishBatchIfReady() {
        guard isRunning, waitingDownloads.isEmpty, downloads.isEmpty else { return }
        isRunning = false
        batchSummary = BatchSummary(tasks: rows.filter { batchIDs.contains($0.id) })
        batchIDs.removeAll()
    }
    private var cookieArguments: [String] {
        guard let session, let cookieFile = session.cookieFile else { return [] }
        return ["--cookies-file", cookieFile.path] + session.authDomains.flatMap { ["--auth-domain", $0] }
    }
    private func mutate(_ id: UUID, _ change: (inout DownloadTask) -> Void) {
        if let index = rows.firstIndex(where: { $0.id == id }) { change(&rows[index]) }
    }
    private func showNextOverwrite() {
        if overwritePrompt == nil && !pendingOverwrites.isEmpty { overwritePrompt = pendingOverwrites.removeFirst() }
    }
    private func discardOverwrite(_ taskID: UUID) {
        pendingOverwrites.removeAll { $0.taskID == taskID }
        if overwritePrompt?.taskID == taskID { overwritePrompt = nil; showNextOverwrite() }
    }
    private func appendLog(_ line: String) {
        guard !line.isEmpty else { return }
        logLines.append(Self.sanitize(line))
        if logLines.count > 1200 { logLines.removeFirst(logLines.count - 1000) }
    }
    private func reportCookieFallback() {
        guard !cookieFallbackWarningShown else { return }
        cookieFallbackWarningShown = true
        // Nur ein lokalisierbarer Hinweis, keine Cookies oder privaten URLs.
        appendLog("cookiesFallbackWithoutAuthentication")
    }
    private static func collectJSON<T: Decodable & Sendable>(from run: any BackendRunning, type: T.Type) async -> (value: T?, exitCode: Int32?) {
        var text = ""; var exitCode: Int32?
        for await output in run.events {
            switch output {
            case .line(let line): text += line + "\n"
            case .exited(let code): exitCode = code
            }
        }
        let decoder = JSONDecoder()
        if let data = text.data(using: .utf8), let value = try? decoder.decode(T.self, from: data) { return (value, exitCode) }
        for line in text.split(separator: "\n").reversed() {
            if let data = line.data(using: .utf8), let value = try? decoder.decode(T.self, from: data) { return (value, exitCode) }
        }
        return (nil, exitCode)
    }
    public static func sanitize(_ text: String) -> String {
        var value = text
        value = value.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "[home]")
        // URLComponents erkennt auch Prozentkodierung in Parameternamen.
        let privateKeys: Set<String> = ["access_token", "token", "auth", "signature", "sig", "key", "jwt", "policy", "password", "h"]
        if let detector = try? NSRegularExpression(pattern: #"https?://[^\s<>\"']+"#, options: .caseInsensitive) {
            let matches = detector.matches(in: value, range: NSRange(value.startIndex..., in: value))
            for match in matches.reversed() {
                guard let range = Range(match.range, in: value), var url = URLComponents(string: String(value[range])) else { continue }
                if url.user != nil { url.user = "[private]" }
                if url.password != nil { url.password = "[private]" }
                if let items = url.queryItems {
                    url.queryItems = items.map { privateKeys.contains($0.name.lowercased()) ? URLQueryItem(name: $0.name, value: "[private]") : $0 }
                }
                // Nicht gelistete Vimeo-Links können den Schlüssel im Pfad haben.
                if ["vimeo.com", "www.vimeo.com"].contains(url.host?.lowercased() ?? "") {
                    url.path = url.path.replacingOccurrences(of: #"^(/[0-9]+/)[A-Za-z0-9_-]+"#, with: "$1[private]", options: .regularExpression)
                }
                if let replacement = url.string { value.replaceSubrange(range, with: replacement) }
            }
        }
        for pattern in [#"(?i)(cookie|set-cookie|authorization)\s*[:=][^\n\r]+"#, #"(?i)(?<![A-Za-z0-9_%])(?:access_token|token|password|signature|sig|auth|key|jwt|policy|h)=([^&\s]+)"#, #"/Users/[^/\s]+(?:/Library/[^\n\r]*)?"#] {
            value = value.replacingOccurrences(of: pattern, with: "[private]", options: .regularExpression)
        }
        return String(value.prefix(4000))
    }
}

private final class PrivateCookieSession {
    let directory: URL
    let authDomains: [String]
    var cookieFile: URL?
    init(authDomains: [String] = []) throws {
        self.authDomains = authDomains
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("openmedia-session-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    }
    func acceptCookie(path: String) -> Bool {
        let url = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        let root = directory.resolvingSymlinksInPath().standardizedFileURL.path + "/"
        guard url.path.hasPrefix(root), FileManager.default.isReadableFile(atPath: url.path) else { return false }
        do { try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path) }
        catch { return false }
        cookieFile = url; return true
    }
    deinit { try? FileManager.default.removeItem(at: directory) }
}
