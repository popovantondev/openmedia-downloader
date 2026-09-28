import Foundation
import OpenMediaCore
import SwiftUI

extension AppCopy {
    func authenticationError(code: String?, fallback: String?) -> String {
        switch code {
        case "browserCookieAccessDenied": return self[.authAccessDenied]
        case "invalidCookieFile": return self[.authInvalidFile]
        case "authenticationTimedOut": return self[.authTimedOut]
        case "authenticationCheckFailed", "error": return self[.authCheckFailed]
        default: return fallback.flatMap { $0.isEmpty ? nil : $0 } ?? self[.authError]
        }
    }

    func diagnosticError(code: String?, fallback: String?) -> String? {
        code == "backendOutputDidNotClose" ? self[.backendOutputInterrupted] : fallback
    }

    func media(_ media: MediaKind) -> String {
        switch media { case .video: self[.video]; case .aac: self[.aac]; case .mp3: self[.mp3] }
    }
    func mode(_ mode: TransferMode) -> String {
        switch mode { case .auto: self[.automatic]; case .direct: self[.direct]; case .chunks: self[.chunks] }
    }
    func quality(_ quality: String) -> String {
        switch quality {
        case "best": self[.best]
        case "4320": "4320p · 8K"
        case "2160": "2160p · 4K"
        case "1440": "1440p · 2K"
        default: quality.hasSuffix("k") ? "\(quality.dropLast()) kbps" : "\(quality)p"
        }
    }
    func stage(_ stage: TaskStage) -> String {
        switch stage {
        case .queued: self[.stageQueued]
        case .inspecting: self[.stageInspecting]
        case .scheduled: self[.stageScheduled]
        case .live: self[.stageLive]
        case .endedProcessing: self[.stageEndedProcessing]
        case .finalizing: self[.stageFinalizing]
        case .preparing: self[.stagePreparing]
        case .downloading: self[.stageDownloading]
        case .merging: self[.stageMerging]
        case .waitingForOverwrite: self[.stageOverwrite]
        case .completed: self[.stageCompleted]
        case .skipped: self[.stageSkipped]
        case .cancelled: self[.stageCancelled]
        case .failed: self[.stageFailed]
        case .authenticationRequired: self[.stageAuthentication]
        }
    }
    func availability(_ value: Availability) -> String {
        switch value {
        case .available: self[.available]
        case .unknown: self[.availabilityUnknown]
        case .authenticationRequired: self[.authRequired]
        case .unavailable: self[.unavailable]
        }
    }
    func estimate(_ estimate: SizeEstimate?) -> String {
        guard let estimate else { return "—" }
        return (estimate.approximate ? "≈ " : "") + Self.bytes(estimate.bytes)
    }
    func logLine(_ line: String) -> String {
        if line == "cookiesFallbackWithoutAuthentication" { return self[.cookiesFallbackWithoutAuthentication] }
        if line == "publicAccessFallback" { return self[.publicAccessFallback] }
        if line == "authenticationAnonymous" { return self[.authPublic] }
        let fields = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        guard fields.count == 2 else { return line }
        let labels: [String: CopyKey] = [
            "queued": .stageQueued, "authenticationRequired": .authRequired,
            "failed": .stageFailed, "playlistReady": .playlistReady,
            "completed": .stageCompleted, "skipped": .stageSkipped,
            "cancelled": .stageCancelled, "inspectionFailed": .stageFailed,
            "duplicateVariantsSkipped": .duplicateNotice
        ]
        guard let key = labels[String(fields[0])] else { return line }
        return self[key] + ":" + fields[1]
    }
    static func bytes(_ value: Int64) -> String { ByteCountFormatter.string(fromByteCount: value, countStyle: .file) }
    static func duration(_ seconds: Double) -> String {
        let seconds = max(0, Int(seconds.isFinite ? seconds : 0))
        return seconds >= 3600
            ? String(format: "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
            : String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}

struct DownloadProgressCell: View {
    let task: DownloadTask
    let copy: AppCopy
    var retry: (() -> Void)?

    private var fraction: Double {
        task.stage == .completed ? 1 : max(0, min(1, task.progress.fraction ?? 0))
    }
    private var progressText: String {
        guard task.stage == .downloading else { return copy.stage(task.stage) }
        let percent = task.progress.fraction.map { "\(Int(max(0, min(1, $0)) * 100))%" }
        if let index = task.progress.fragmentIndex, let count = task.progress.fragmentCount, count > 0 {
            return "\(index) / \(count)" + (percent.map { " · \($0)" } ?? "")
        }
        return percent ?? copy.stage(task.stage)
    }
    private var details: String {
        // Empfangene Bytes sind nach einer MP3-Konvertierung nicht die Dateigröße.
        guard task.stage == .downloading else { return "" }
        var pieces: [String] = []
        if let bytes = task.progress.downloadedBytes { pieces.append(AppCopy.bytes(bytes)) }
        if let speed = task.progress.speedBytesPerSecond, speed.isFinite, speed > 0 {
            pieces.append(AppCopy.bytes(Int64(min(speed, Double(Int64.max / 2)))) + copy[.perSecond])
        }
        if let eta = task.progress.etaSeconds { pieces.append("\(AppCopy.duration(eta)) \(copy[.remaining])") }
        return pieces.joined(separator: " · ")
    }

    var body: some View {
        VStack(spacing: 4) {
            GeometryReader { geometry in
                ZStack(alignment: .center) {
                    RoundedRectangle(cornerRadius: 8).fill(Color.blue.opacity(0.08))
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.blue)
                        .frame(width: geometry.size.width * fraction)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    HStack(spacing: 6) {
                        if [.inspecting, .preparing, .merging, .finalizing].contains(task.stage) || (task.stage == .downloading && task.progress.fraction == nil) {
                            ProgressView().controlSize(.mini).frame(width: 12, height: 12)
                        }
                        Text(progressText).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    }
                    .foregroundStyle(fraction > 0.65 ? Color.white : Color.primary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                }
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(task.stage == .failed ? Color.red.opacity(0.65) : Color.blue.opacity(0.35)))
            }
            .frame(height: 30)
            if [.failed, .cancelled, .authenticationRequired].contains(task.stage), let retry {
                Button(action: retry) { Label(copy[.retry], systemImage: "arrow.clockwise") }
                    .buttonStyle(.link).font(.system(size: 10)).help(copy[.retryHint])
            } else {
                Text(details.isEmpty ? " " : details)
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .help(copy.diagnosticError(code: task.errorCode, fallback: task.errorMessage) ?? task.outputPath ?? copy.stage(task.stage))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(copy.stage(task.stage)), \(progressText), \(details)")
    }
}

struct MediaPicker: View {
    @Binding var value: MediaKind
    let copy: AppCopy
    var body: some View {
        Picker(copy[.format], selection: $value) {
            ForEach(MediaKind.allCases, id: \.self) { Text(copy.media($0)).tag($0) }
        }.labelsHidden()
    }
}

struct QualityPicker: View {
    @Binding var value: String
    let media: MediaKind
    let copy: AppCopy
    var body: some View {
        Picker(copy[.quality], selection: $value) {
            ForEach(QualityOptions.values(for: media), id: \.self) { Text(copy.quality($0)).tag($0) }
        }.labelsHidden().disabled(media == .aac)
    }
}

struct ModePicker: View {
    @Binding var value: TransferMode
    let copy: AppCopy
    var body: some View {
        Picker(copy[.mode], selection: $value) {
            ForEach(TransferMode.allCases, id: \.self) { Text(copy.mode($0)).tag($0) }
        }.labelsHidden()
    }
}
