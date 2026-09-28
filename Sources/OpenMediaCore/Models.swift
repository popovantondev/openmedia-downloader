import Foundation

public enum MediaKind: String, Codable, CaseIterable, Sendable { case video, aac, mp3 }
public enum TransferMode: String, Codable, CaseIterable, Sendable { case auto, direct, chunks }
public enum Availability: String, Codable, Sendable { case available, unknown, authenticationRequired, unavailable }
public enum StreamState: String, Codable, Sendable { case scheduled, live, endedProcessing, vod, regular }
public enum TaskStage: String, Codable, Sendable {
    case queued, inspecting, scheduled, live, endedProcessing, finalizing, preparing, downloading, merging, waitingForOverwrite
    case completed, skipped, cancelled, failed, authenticationRequired

    public var isTerminal: Bool {
        [.completed, .skipped, .cancelled, .failed, .authenticationRequired].contains(self)
    }
    public var isActive: Bool { [.preparing, .live, .finalizing, .downloading, .merging, .waitingForOverwrite].contains(self) }
}

public enum QualityOptions {
    public static func values(for media: MediaKind) -> [String] {
        switch media {
        case .video: ["best", "4320", "2160", "1440", "1080", "720", "540", "480", "360", "240", "144"]
        case .aac: ["best"]
        case .mp3: ["320k", "256k", "192k", "128k"]
        }
    }
}

public struct SizeEstimate: Codable, Equatable, Sendable {
    public var media: MediaKind
    public var quality: String
    public var mode: TransferMode
    public var bytes: Int64
    public var approximate: Bool
    public var actualQuality: String?
    public init(media: MediaKind, quality: String, mode: TransferMode = .auto, bytes: Int64, approximate: Bool, actualQuality: String? = nil) {
        self.media = media; self.quality = quality; self.mode = mode
        self.bytes = bytes; self.approximate = approximate; self.actualQuality = actualQuality
    }
}

public struct MediaEntry: Codable, Identifiable, Equatable, Sendable {
    public var id: String { url }
    public var url: String
    public var title: String
    public var duration: Double?
    public var availableHeights: [Int]
    public var availability: Availability
    public var error: String?
    public var estimates: [SizeEstimate]
    public var streamState: StreamState
    public var fromStartSupported: Bool
    public var fromStartReason: String?
    public var embedRefererOrigin: String?
    public init(url: String, title: String, duration: Double? = nil, availableHeights: [Int] = [], availability: Availability = .available, error: String? = nil, estimates: [SizeEstimate] = [], streamState: StreamState = .regular, fromStartSupported: Bool = false, fromStartReason: String? = nil, embedRefererOrigin: String? = nil) {
        self.url = url; self.title = title; self.duration = duration
        self.availableHeights = availableHeights; self.availability = availability
        self.error = error; self.estimates = estimates; self.streamState = streamState; self.fromStartSupported = fromStartSupported; self.fromStartReason = fromStartReason; self.embedRefererOrigin = embedRefererOrigin
    }
    enum CodingKeys: String, CodingKey { case url, title, duration, availableHeights, availability, error, estimates, streamState, fromStartSupported, fromStartReason, embedRefererOrigin }
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? url
        duration = try c.decodeIfPresent(Double.self, forKey: .duration)
        availableHeights = try c.decodeIfPresent([Int].self, forKey: .availableHeights) ?? []
        availability = try c.decodeIfPresent(Availability.self, forKey: .availability) ?? .unknown
        error = try c.decodeIfPresent(String.self, forKey: .error)
        estimates = try c.decodeIfPresent([SizeEstimate].self, forKey: .estimates) ?? []
        streamState = try c.decodeIfPresent(StreamState.self, forKey: .streamState) ?? .regular
        fromStartSupported = try c.decodeIfPresent(Bool.self, forKey: .fromStartSupported) ?? false
        fromStartReason = try c.decodeIfPresent(String.self, forKey: .fromStartReason)
        embedRefererOrigin = try c.decodeIfPresent(String.self, forKey: .embedRefererOrigin)
    }
}

public struct DownloadProgress: Equatable, Sendable {
    public var fraction: Double?
    public var downloadedBytes: Int64?
    public var totalBytes: Int64?
    public var speedBytesPerSecond: Double?
    public var etaSeconds: Double?
    public var elapsedSeconds: Double?
    public var fragmentIndex: Int?
    public var fragmentCount: Int?
    public init(fraction: Double? = nil, downloadedBytes: Int64? = nil, totalBytes: Int64? = nil, speedBytesPerSecond: Double? = nil, etaSeconds: Double? = nil, elapsedSeconds: Double? = nil, fragmentIndex: Int? = nil, fragmentCount: Int? = nil) {
        self.fraction = fraction; self.downloadedBytes = downloadedBytes; self.totalBytes = totalBytes
        self.speedBytesPerSecond = speedBytesPerSecond; self.etaSeconds = etaSeconds; self.elapsedSeconds = elapsedSeconds
        self.fragmentIndex = fragmentIndex; self.fragmentCount = fragmentCount
    }
}

public struct DownloadTask: Identifiable, Equatable, Sendable {
    public let id: UUID
    public var sourceURL: String
    public var url: String
    public var title: String
    public var media: MediaKind
    public var quality: String
    public var mode: TransferMode
    public var stage: TaskStage
    public var progress = DownloadProgress()
    public var estimates: [SizeEstimate]
    public var availableHeights: [Int]
    public var duration: Double?
    public var streamState: StreamState
    public var fromStartSupported: Bool
    public var fromStartReason: String?
    public var embedRefererOrigin: String?
    public var streamStart: String = "now"
    public var errorMessage: String?
    public var errorCode: String?
    public var outputPath: String?
    public init(id: UUID = UUID(), entry: MediaEntry, sourceURL: String? = nil, media: MediaKind = .video, quality: String = "best", mode: TransferMode = .auto, stage: TaskStage = .queued) {
        self.id = id; self.sourceURL = sourceURL ?? entry.url; self.url = entry.url; self.title = entry.title
        self.media = media; self.quality = quality; self.mode = mode; self.stage = stage
        self.estimates = entry.estimates; self.availableHeights = entry.availableHeights; self.duration = entry.duration
        self.streamState = entry.streamState; self.fromStartSupported = entry.fromStartSupported; self.fromStartReason = entry.fromStartReason
        self.embedRefererOrigin = entry.embedRefererOrigin
        self.errorMessage = entry.error
    }
    public var variantKey: String { [url, media.rawValue, quality, mode.rawValue].joined(separator: "\u{1F}") }
    public var sizeEstimate: SizeEstimate? {
        estimates.first { $0.media == media && $0.quality == quality && $0.mode == mode && $0.bytes > 0 }
    }
    public var estimatedBytes: Int64? { sizeEstimate?.bytes }
    public var estimateIsApproximate: Bool { sizeEstimate?.approximate ?? true }
}

public struct QueueSize: Equatable, Sendable {
    public var knownBytes: Int64 = 0
    public var unknownCount = 0
    public var approximate = false
    public init(tasks: [DownloadTask]) {
        for task in tasks {
            if let estimate = task.sizeEstimate {
                let (sum, overflow) = knownBytes.addingReportingOverflow(estimate.bytes)
                knownBytes = overflow ? Int64.max : sum
                approximate = approximate || estimate.approximate
            } else { unknownCount += 1 }
        }
    }
}

public struct PlaylistGroup: Identifiable, Equatable, Sendable {
    public let id: UUID
    public var sourceURL: String
    public var title: String
    public var entries: [MediaEntry]
    public init(id: UUID = UUID(), sourceURL: String, title: String, entries: [MediaEntry]) {
        self.id = id; self.sourceURL = sourceURL; self.title = title; self.entries = entries
    }
}

public struct PlaylistSelection: Identifiable, Equatable, Sendable {
    public var id: UUID
    public var entryID: String
    public var media: MediaKind
    public var quality: String
    public var mode: TransferMode
    public init(id: UUID = UUID(), entryID: String, media: MediaKind = .video, quality: String = "best", mode: TransferMode = .auto) {
        self.id = id; self.entryID = entryID; self.media = media; self.quality = quality; self.mode = mode
    }
}

public enum AuthChoice: Equatable, Sendable { case anonymous, browser(String), cookiesFile(URL) }
public struct AuthPrompt: Identifiable, Equatable, Sendable {
    public let id = UUID()
    public var errorCode: String?
    public var message: String?
    public init(errorCode: String? = nil, message: String? = nil) { self.errorCode = errorCode; self.message = message }
}
public struct OverwritePrompt: Identifiable, Equatable, Sendable {
    public var id: UUID { taskID }
    public let taskID: UUID
    public let path: String
    public init(taskID: UUID, path: String) { self.taskID = taskID; self.path = path }
}
public struct BatchSummary: Identifiable, Equatable, Sendable {
    public let id = UUID()
    public var completed: Int
    public var skipped: Int
    public var failed: Int
    public var cancelled: Int
    public var authenticationRequired: Int
    public init(tasks: [DownloadTask]) {
        completed = tasks.filter { $0.stage == .completed }.count
        skipped = tasks.filter { $0.stage == .skipped }.count
        failed = tasks.filter { $0.stage == .failed }.count
        cancelled = tasks.filter { $0.stage == .cancelled }.count
        authenticationRequired = tasks.filter { $0.stage == .authenticationRequired }.count
    }
}
