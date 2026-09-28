import Foundation
import Darwin

public enum BackendOutput: Equatable, Sendable { case line(String), exited(Int32) }
public protocol BackendRunning: AnyObject, Sendable {
    var events: AsyncStream<BackendOutput> { get }
    func send(_ text: String)
    func cancel()
}
public protocol BackendClient: Sendable {
    func launch(arguments: [String]) throws -> any BackendRunning
}

public enum BackendClientError: Error, LocalizedError {
    case executableMissing
    public var errorDescription: String? { "backendExecutableMissing" }
}

/// Ein Puffer behält auch UTF-8-Zeichen, die über zwei Datenblöcke verteilt sind.
public struct LineFramer: Sendable {
    private var buffer = Data()
    public init() {}
    public mutating func append(_ data: Data, endOfFile: Bool = false) -> [String] {
        buffer.append(data)
        var lines: [String] = []
        while let index = buffer.firstIndex(where: { $0 == 10 || $0 == 13 }) {
            let prefix = buffer[..<index]
            if !prefix.isEmpty { lines.append(String(decoding: prefix, as: UTF8.self)) }
            buffer.removeSubrange(...index)
        }
        if endOfFile && !buffer.isEmpty {
            lines.append(String(decoding: buffer, as: UTF8.self)); buffer.removeAll()
        }
        // Ein kaputter Prozess darf den Speicher nicht unbegrenzt füllen.
        if buffer.count > 4_194_304 {
            lines.append(String(decoding: buffer, as: UTF8.self)); buffer.removeAll()
        }
        return lines
    }
}

public struct ProcessBackendClient: BackendClient {
    public let executable: URL?
    public let prefixArguments: [String]
    private let outputDrainTimeout: TimeInterval
    public init(executable: URL? = nil, prefixArguments: [String] = [], outputDrainTimeout: TimeInterval = 3) {
        self.executable = executable ?? Bundle.main.resourceURL?.appendingPathComponent("backend/omd_backend")
        self.prefixArguments = prefixArguments
        self.outputDrainTimeout = max(0.1, outputDrainTimeout)
    }
    public func launch(arguments: [String]) throws -> any BackendRunning {
        guard let executable, FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw BackendClientError.executableMissing
        }
        return try ProcessRun(executable: executable, arguments: prefixArguments + arguments, outputDrainTimeout: outputDrainTimeout)
    }
}

private final class ProcessRun: BackendRunning, @unchecked Sendable {
    let events: AsyncStream<BackendOutput>
    private let continuation: AsyncStream<BackendOutput>.Continuation
    private let process = Process()
    private let output = Pipe()
    private let input = Pipe()
    private let lock = NSLock()
    private let inputQueue = DispatchQueue(label: "OpenMediaCore.ProcessRun.stdin")
    private let outputReadLock = NSLock()
    private var framer = LineFramer()
    private var outputClosed = false
    private var exitStatus: Int32?
    private var finished = false
    private var didCancel = false
    private let outputDrainTimeout: TimeInterval
    private var lifetime: ProcessRun?

    init(executable: URL, arguments: [String], outputDrainTimeout: TimeInterval) throws {
        self.outputDrainTimeout = outputDrainTimeout
        let stream = AsyncStream<BackendOutput>.makeStream()
        events = stream.stream; continuation = stream.continuation
        process.executableURL = executable; process.arguments = arguments
        process.standardOutput = output; process.standardError = output; process.standardInput = input
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"; environment["NO_COLOR"] = "1"
        process.environment = environment
        let descriptor = output.fileHandleForReading.fileDescriptor
        _ = fcntl(descriptor, F_SETFL, fcntl(descriptor, F_GETFL) | O_NONBLOCK)
        output.fileHandleForReading.readabilityHandler = { [weak self] _ in
            self?.readAvailableBytes(descriptor: descriptor)
        }
        process.terminationHandler = { [weak self] process in self?.terminated(process.terminationStatus) }
        do {
            try process.run()
            lock.withLock { if !finished { lifetime = self } }
        }
        catch {
            output.fileHandleForReading.readabilityHandler = nil
            continuation.finish()
            throw error
        }
        // Nur das Kind schreibt. Sonst käme im Leser nie das Dateiende an.
        try? output.fileHandleForWriting.close()
        try? input.fileHandleForReading.close()
    }

    func send(_ text: String) {
        inputQueue.async { [weak self] in
            guard let self else { return }
            self.lock.withLock {
                guard !self.finished, !self.didCancel, let data = text.data(using: .utf8) else { return }
                try? self.input.fileHandleForWriting.write(contentsOf: data)
            }
        }
    }

    func cancel() {
        let shouldCancel = lock.withLock { () -> Bool in
            guard !finished, !didCancel else { return false }
            didCancel = true; return true
        }
        guard shouldCancel else { return }
        let pid = process.processIdentifier
        guard pid > 0 else { return }
        let ownsGroup = hasOwnProcessGroup(pid)
        if ownsGroup { _ = kill(-pid, SIGTERM) }
        else if process.isRunning { process.terminate() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [self] in
            guard !lock.withLock({ finished }) else { return }
            // Auch nach dem Ende des Elternprozesses können Kinder noch schreiben.
            if ownsGroup { _ = kill(-pid, SIGKILL) }
            else if self.process.isRunning { _ = kill(pid, SIGKILL) }
        }
    }

    private func consume(_ data: Data) {
        lock.withLock {
            guard !finished else { return }
            for line in framer.append(data, endOfFile: data.isEmpty) { continuation.yield(.line(line)) }
            if data.isEmpty { outputClosed = true }
            finishIfReady()
        }
    }
    private func readAvailableBytes(descriptor: Int32) {
        outputReadLock.withLock {
            guard !lock.withLock({ finished }) else { return }
            // FileHandle.read(upToCount:) wartet auf macOS bis zur vollen Länge.
            // Ein einzelner nicht-blockierender read liefert Fortschritt sofort.
            var bytes = [UInt8](repeating: 0, count: 65_536)
            let count = bytes.withUnsafeMutableBytes { Darwin.read(descriptor, $0.baseAddress, $0.count) }
            if count > 0 { consume(Data(bytes.prefix(count))) }
            else if count == 0 {
                output.fileHandleForReading.readabilityHandler = nil
                consume(Data())
            } else if errno != EAGAIN && errno != EINTR {
                output.fileHandleForReading.readabilityHandler = nil
                consume(Data())
            }
        }
    }
    private func terminated(_ status: Int32) {
        lock.withLock { exitStatus = status; finishIfReady() }
        DispatchQueue.global().asyncAfter(deadline: .now() + outputDrainTimeout) { [self] in
            finishStalledOutput()
        }
    }
    private func finishStalledOutput() {
        let needsCleanup = lock.withLock { () -> Bool in
            guard !finished, exitStatus != nil, !outputClosed else { return false }
            exitStatus = -1
            continuation.yield(.line(#"OMD_EVENT:{"type":"error","code":"backendOutputDidNotClose","message":"backendOutputDidNotClose"}"#))
            return true
        }
        guard needsCleanup else { return }
        let pid = process.processIdentifier
        // Die PID bleibt als Gruppen-ID erhalten, wenn nur der Elternprozess endet.
        if hasOwnProcessGroup(pid) { _ = kill(-pid, SIGKILL) }
        output.fileHandleForReading.readabilityHandler = nil
        outputReadLock.withLock {
            lock.withLock {
                guard !finished else { return }
                for line in framer.append(Data(), endOfFile: true) { continuation.yield(.line(line)) }
                outputClosed = true
                finishIfReady()
            }
            try? output.fileHandleForReading.close()
        }
    }
    private func hasOwnProcessGroup(_ pid: Int32) -> Bool {
        guard pid > 0 else { return false }
        let group = getpgid(pid)
        if group == pid { return true }
        // Ein lebender Prozess in einer fremden Gruppe darf diese nicht beenden.
        return group == -1 && kill(-pid, 0) == 0
    }
    private func finishIfReady() {
        guard !finished, outputClosed, let exitStatus else { return }
        finished = true
        try? input.fileHandleForWriting.close()
        continuation.yield(.exited(exitStatus)); continuation.finish()
        lifetime = nil
    }
}

public struct BackendEvent: Decodable, Sendable {
    public var type: String
    public var requestId: String?
    public var generation: Int?
    public var source: String?
    public var index: Int?
    public var itemId: String?
    public var playlistPosition: Int?
    public var taskId: String?
    public var title: String?
    public var url: String?
    public var availability: Availability?
    public var entry: MediaEntry?
    public var ok: Bool?
    public var isPlaylist: Bool?
    public var count: Int?
    public var error: String?
    public var stage: String?
    public var progress: Double?
    public var downloadedBytes: Int64?
    public var totalBytes: Int64?
    public var speedBytesPerSecond: Double?
    public var etaSeconds: Double?
    public var fragmentIndex: Int?
    public var fragmentCount: Int?
    public var elapsedSeconds: Double?
    public var path: String?
    public var code: String?
    public var message: String?
    public var browser: String?
    public var fallback: String?
    public static func parse(_ line: String) -> BackendEvent? {
        guard line.hasPrefix("OMD_EVENT:"), let data = line.dropFirst("OMD_EVENT:".count).data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(Self.self, from: data)
    }
}

struct InspectionEventIdentity: Equatable, Sendable {
    let requestId: String
    let generation: Int
    let source: String

    func accepts(_ event: BackendEvent) -> Bool {
        event.requestId == requestId && event.generation == generation && event.source == source
    }
}

struct BackendWarning: Decodable, Sendable {
    var code: String
    var browser: String?
    var fallback: String?
}

struct InspectionResponse: Decodable, Sendable {
    var ok: Bool
    var source: String?
    var title: String?
    var isPlaylist: Bool?
    var entries: [MediaEntry]?
    var errorCode: String?
    var error: String?
    var warnings: [BackendWarning]?
    var cookieFallbackUsed: Bool?
}
struct AuthResponse: Decodable, Sendable {
    var ok: Bool
    var status: String
    var cookieFile: String?
    var error: String?
    var message: String?
    var detail: String? { message ?? error }
}
