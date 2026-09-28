import AppKit
import OpenMediaCore
import SwiftUI

private enum AppSheet: Identifiable {
    case firstLaunchLanguage
    case authorization
    case playlist(UUID)
    var id: String {
        switch self {
        case .firstLaunchLanguage: "firstLaunchLanguage"
        case .authorization: "authorization"
        case .playlist(let groupID): groupID.uuidString
        }
    }
}

private enum AppAlert: Identifiable {
    case overwrite(OverwritePrompt)
    case completion(BatchSummary)
    var id: UUID {
        switch self { case .overwrite(let value): value.id; case .completion(let value): value.id }
    }
}

struct MainView: View {
    @ObservedObject var coordinator: DownloadCoordinator
    var languageChanged: () -> Void = {}
    @AppStorage("interfaceLanguage") private var languageCode = InterfaceLanguage.german.rawValue
    @AppStorage("interfaceAppearance") private var appearanceCode = InterfaceAppearance.system.rawValue
    @AppStorage("firstLaunchLanguageChosen") private var firstLaunchLanguageChosen = false
    @AppStorage("maxConcurrentFiles") private var storedMaxConcurrentFiles = 4
    @AppStorage("fragmentsPerFile") private var storedFragmentsPerFile = 4
    @State private var globalMedia = MediaKind.video
    @State private var globalQuality = "best"
    @State private var sheet: AppSheet?
    @State private var activeAlert: AppAlert?

    private var copy: AppCopy { AppCopy(language: InterfaceLanguage(rawValue: languageCode) ?? .russian) }
    private var canStart: Bool {
        !coordinator.isRunning && !coordinator.isAuthenticating && coordinator.rows.contains { ![.completed, .skipped, .cancelled].contains($0.stage) }
    }

    var body: some View {
        VStack(spacing: 15) {
            header
            inputPanel
            queuePanel
            controls
            statusAndLog
        }
        .padding(20)
        .frame(minWidth: 850, idealWidth: 1150, minHeight: 650, idealHeight: 760)
        .background(Color(nsColor: .windowBackgroundColor))
        .tint(.blue)
        .preferredColorScheme(InterfaceAppearance(rawValue: appearanceCode)?.colorScheme ?? nil)
        .onAppear(perform: fitWindowToScreen)
        .onAppear {
            applyAppearance(appearanceCode)
            coordinator.maxConcurrentFiles = min(16, max(1, storedMaxConcurrentFiles))
            coordinator.fragmentsPerFile = min(32, max(1, storedFragmentsPerFile))
            if !firstLaunchLanguageChosen, sheet == nil { sheet = .firstLaunchLanguage }
        }
        .onChange(of: coordinator.maxConcurrentFiles) { _, value in storedMaxConcurrentFiles = min(16, max(1, value)) }
        .onChange(of: coordinator.fragmentsPerFile) { _, value in storedFragmentsPerFile = min(32, max(1, value)) }
        .onChange(of: appearanceCode) { _, value in
            applyAppearance(value)
            languageChanged()
        }
        .sheet(item: $sheet, onDismiss: synchronizeSheet) { item in
            switch item {
            case .firstLaunchLanguage:
                firstLaunchLanguageSheet
            case .authorization:
                AuthorizationSheet(coordinator: coordinator, copy: copy) { sheet = nil }
            case .playlist(let groupID):
                if let group = coordinator.playlistGroups.first(where: { $0.id == groupID }) {
                    PlaylistSheet(group: group, copy: copy, add: { variants in
                        coordinator.addPlaylistSelection(groupID: groupID, variants: variants)
                        if !coordinator.playlistGroups.contains(where: { $0.id == groupID }) { sheet = nil }
                    }, prioritize: { entryID in
                        coordinator.prioritizePlaylistEntry(groupID: groupID, entryID: entryID)
                    }, skip: {
                        coordinator.dismissPlaylist(groupID)
                        sheet = nil
                    })
                    .interactiveDismissDisabled()
                } else {
                    Color.clear
                }
            }
        }
        .alert(item: $activeAlert, content: makeAlert)
        .onChange(of: coordinator.authPrompt) { _, prompt in
            if prompt == nil, sheet?.id == "authorization", !coordinator.isAuthenticating { sheet = nil }
            synchronizeSheet()
        }
        .onChange(of: coordinator.isAuthenticating) { _, busy in
            if !busy, coordinator.authPrompt == nil, sheet?.id == "authorization" { sheet = nil }
            synchronizeSheet()
        }
        .onChange(of: coordinator.playlistGroups) { _, groups in
            if case .playlist(let groupID)? = sheet,
               !groups.contains(where: { $0.id == groupID }) {
                sheet = nil
            }
            synchronizeSheet()
        }
        .onChange(of: coordinator.overwritePrompt) { _, _ in synchronizeAlert() }
        .onChange(of: coordinator.batchSummary) { _, _ in synchronizeAlert() }
        .onChange(of: globalMedia) { _, media in globalQuality = QualityOptions.values(for: media)[0] }
        .onChange(of: languageCode) { _, _ in languageChanged() }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(nsImage: NSImage(contentsOf: Bundle.main.url(forResource: "AppIcon", withExtension: "icns") ?? URL(fileURLWithPath: "assets/AppIcon.icns")) ?? NSApplication.shared.applicationIconImage)
                .resizable()
                .scaledToFit()
                .frame(width: 48, height: 48)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("OpenMedia Downloader").font(.system(size: 22, weight: .semibold))
                    Text(AppMetadata.version).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        .padding(.horizontal, 7).padding(.vertical, 3)
                        .background(.quaternary, in: Capsule())
                }
                Text(copy[.subtitle]).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Picker(copy[.language], selection: $languageCode) {
                ForEach(InterfaceLanguage.allCases) { Text($0.name).tag($0.rawValue) }
            }
            .labelsHidden().frame(width: 128)
            .help(copy[.language])
            Picker(copy[.appearance], selection: $appearanceCode) {
                Text(copy[.systemAppearance]).tag(InterfaceAppearance.system.rawValue)
                Text(copy[.lightAppearance]).tag(InterfaceAppearance.light.rawValue)
                Text(copy[.darkAppearance]).tag(InterfaceAppearance.dark.rawValue)
            }.labelsHidden().frame(width: 115).help(copy[.appearance])
        }
    }

    private var firstLaunchLanguageSheet: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(copy[.chooseLanguageTitle]).font(.title2.bold())
            Text(copy[.chooseLanguageMessage]).foregroundStyle(.secondary)
            Picker(copy[.language], selection: $languageCode) {
                ForEach(InterfaceLanguage.allCases) { Text($0.name).tag($0.rawValue) }
            }.pickerStyle(.radioGroup)
            HStack { Spacer(); Button(copy[.done]) {
                firstLaunchLanguageChosen = true
                sheet = nil
            }.keyboardShortcut(.defaultAction) }
        }.padding(24).frame(width: 360)
    }

    private func applyAppearance(_ value: String) {
        NSApplication.shared.appearance = value == InterfaceAppearance.light.rawValue ? NSAppearance(named: .aqua) :
            value == InterfaceAppearance.dark.rawValue ? NSAppearance(named: .darkAqua) : nil
    }

    private var inputPanel: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(copy[.links]).font(.callout.weight(.semibold))
                Text(copy[.linksHint]).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
                Button { coordinator.inspectInput(force: true) } label: { Label(copy[.inspect], systemImage: "arrow.clockwise") }
                    .controlSize(.small)
                    .disabled(coordinator.isAuthenticating || coordinator.isRunning)
            }
            LinkEditor(text: Binding(get: { coordinator.inputText }, set: { coordinator.updateInput($0) }), label: copy[.links], help: copy[.linksHint], onEdit: { _ in })
                .frame(height: 83)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 9))
                .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Color.secondary.opacity(0.26)))
        }
    }

    private var queuePanel: some View {
        GeometryReader { geometry in
            ScrollView(.horizontal) {
                VStack(spacing: 0) {
                    tableHeader
                    Divider()
                    if coordinator.rows.isEmpty {
                        VStack(spacing: 11) {
                            Image(systemName: "tray.and.arrow.down").font(.system(size: 31)).foregroundStyle(.tertiary)
                            Text(copy[.emptyQueue]).font(.callout).foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        ScrollView(.vertical) {
                            LazyVStack(spacing: 0) {
                                ForEach(Array(coordinator.rows.enumerated()), id: \.element.id) { index, task in
                                    taskRow(task)
                                        .background(index.isMultiple(of: 2) ? Color.clear : Color.primary.opacity(0.025))
                                    Divider().opacity(0.5)
                                }
                            }
                        }
                    }
                }
                .frame(width: max(QueueColumnMetrics.minimumTableWidth, geometry.size.width), height: geometry.size.height)
            }
        }
        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.18)))
        .frame(minHeight: 235, maxHeight: .infinity)
    }

    private var tableHeader: some View {
        HStack(spacing: QueueColumnMetrics.spacing) {
            Text(copy[.file]).frame(minWidth: QueueColumnMetrics.titleMinimum, maxWidth: .infinity, alignment: .leading)
            Text(copy[.format]).frame(width: QueueColumnMetrics.format)
            Text(copy[.quality]).frame(width: QueueColumnMetrics.quality)
            Text(copy[.mode]).frame(width: QueueColumnMetrics.mode)
            Text(copy[.size]).frame(width: QueueColumnMetrics.size)
            Text(copy[.progress]).frame(width: QueueColumnMetrics.progress)
            Image(systemName: "plus").frame(width: QueueColumnMetrics.action, alignment: .center).accessibilityLabel(copy[.addVariant])
            Color.clear.frame(width: QueueColumnMetrics.action, height: 14)
        }
        .font(.system(size: 11, weight: .semibold))
        .foregroundStyle(.secondary)
        .padding(.leading, QueueColumnMetrics.horizontalInset)
        .padding(.trailing, QueueColumnMetrics.horizontalInset + QueueColumnMetrics.scrollbarInset)
        .frame(height: 40)
        .background(Color.primary.opacity(0.025))
    }

    private func taskRow(_ task: DownloadTask) -> some View {
        HStack(spacing: QueueColumnMetrics.spacing) {
            VStack(alignment: .leading, spacing: 4) {
                Text(task.title).font(.system(size: 12, weight: .medium)).lineLimit(1)
                Text(task.url)
                    .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                if task.streamState == .live {
                    if task.fromStartSupported {
                        Picker(copy[.streamNow], selection: Binding(
                            get: { task.streamStart },
                            set: { _ = coordinator.chooseStreamStart($0, for: task.id) }
                        )) {
                            Text(copy[.streamNow]).tag("now")
                            Text(copy[.streamFromStart]).tag("from-start")
                        }
                        .labelsHidden().pickerStyle(.segmented).frame(maxWidth: 250)
                        .disabled(task.stage.isActive || coordinator.isRunning)
                    } else {
                        HStack(spacing: 4) {
                            Text(copy[.streamNow])
                            Text("·")
                            Text(copy[.fromStartUnavailable])
                        }.font(.system(size: 10)).foregroundStyle(.secondary)
                            .help(task.fromStartReason == "archiveUnavailable" ? copy[.fromStartUnavailable] : (task.fromStartReason ?? copy[.fromStartUnavailable]))
                    }
                }
            }
            .frame(minWidth: QueueColumnMetrics.titleMinimum, maxWidth: .infinity, alignment: .leading)
            .help(task.title)
            MediaPicker(value: Binding(get: { task.media }, set: { coordinator.updateVariant(task.id, media: $0) }), copy: copy)
                .frame(width: QueueColumnMetrics.format).disabled(task.stage.isActive || task.stage == .inspecting)
            QualityPicker(value: Binding(get: { task.quality }, set: { coordinator.updateVariant(task.id, quality: $0) }), media: task.media, copy: copy)
                .frame(width: QueueColumnMetrics.quality).disabled(task.stage.isActive || task.stage == .inspecting)
            ModePicker(value: Binding(get: { task.mode }, set: { coordinator.updateVariant(task.id, mode: $0) }), copy: copy)
                .frame(width: QueueColumnMetrics.mode).disabled(task.stage.isActive || task.stage == .inspecting)
            VStack(spacing: 3) {
                Text(copy.estimate(task.sizeEstimate)).font(.system(size: 11)).monospacedDigit()
                if let actual = task.sizeEstimate?.actualQuality, actual != task.quality {
                    Text(copy.quality(actual)).font(.system(size: 9)).foregroundStyle(.secondary)
                }
            }
            .frame(width: QueueColumnMetrics.size).help(task.sizeEstimate == nil ? copy[.unknownSize] : copy[.estimatesHint])
            DownloadProgressCell(task: task, copy: copy, retry: { coordinator.retry(task.id) }).frame(width: QueueColumnMetrics.progress)
            SquareSymbolButton(symbol: "plus", help: copy[.addVariant]) { coordinator.addVariant(for: task.id) }
                .disabled(task.stage == .inspecting)
            if task.streamState == .live && task.stage.isActive {
                Button(copy[.stopAndSave], systemImage: "stop.circle") { coordinator.stopAndSave(task.id) }
                    .labelStyle(.iconOnly).help(copy[.stopAndSave]).disabled(task.stage == .finalizing || task.stage == .merging)
            } else {
                SquareSymbolButton(symbol: "xmark", help: copy[.cancelTask], destructive: true) { coordinator.removeOrCancel(task.id) }
            }
        }
        .controlSize(.small)
        .padding(.leading, QueueColumnMetrics.horizontalInset)
        .padding(.trailing, QueueColumnMetrics.horizontalInset + QueueColumnMetrics.scrollbarInset)
        .padding(.vertical, 8)
        .frame(minHeight: 64)
        .contextMenu {
            Button(copy[.addVariant]) { coordinator.addVariant(for: task.id) }.disabled(task.stage == .inspecting)
            if task.streamState == .live && task.stage.isActive { Button(copy[.stopAndSave]) { coordinator.stopAndSave(task.id) }.disabled(task.stage == .finalizing) }
            if [.failed, .cancelled, .authenticationRequired].contains(task.stage) {
                Button(copy[.retry]) { coordinator.retry(task.id) }
            }
            Button(copy[.cancelTask], role: .destructive) { coordinator.removeOrCancel(task.id) }
        }
    }

    private var controls: some View {
        VStack(spacing: 12) {
            HStack(spacing: 9) {
                Text(copy[.allFormats]).font(.caption).foregroundStyle(.secondary)
                MediaPicker(value: $globalMedia, copy: copy).frame(width: 112)
                Text(copy[.allQuality]).font(.caption).foregroundStyle(.secondary)
                QualityPicker(value: $globalQuality, media: globalMedia, copy: copy).frame(width: 113)
                Button(copy[.applyAll]) { coordinator.applyToAll(media: globalMedia, quality: globalQuality) }
                    .disabled(coordinator.rows.isEmpty || coordinator.isRunning)
                Spacer(minLength: 5)
                Text(copy[.parallelFiles]).font(.caption).foregroundStyle(.secondary)
                Stepper(value: $coordinator.maxConcurrentFiles, in: 1...16) {
                    Text("\(coordinator.maxConcurrentFiles)").monospacedDigit().frame(width: 22)
                }.fixedSize().disabled(coordinator.isRunning)
                    .accessibilityLabel(copy[.parallelFiles])
                    .accessibilityValue(String(coordinator.maxConcurrentFiles))
                Text(copy[.fragments]).font(.caption).foregroundStyle(.secondary)
                Stepper(value: $coordinator.fragmentsPerFile, in: 1...32) {
                    Text("\(coordinator.fragmentsPerFile)").monospacedDigit().frame(width: 22)
                }.fixedSize().disabled(coordinator.isRunning)
                    .accessibilityLabel(copy[.fragments])
                    .accessibilityValue(String(coordinator.fragmentsPerFile))
            }
            .controlSize(.small)
            HStack(spacing: 10) {
                Button { coordinator.requestAuthentication() } label: {
                    Label(copy[.authorization], systemImage: coordinator.authenticationStatus == "ready" ? "lock.shield.fill" : "lock.shield")
                }.disabled(coordinator.isRunning || coordinator.isAuthenticating)
                Button(copy[.folder]) {
                    if let folder = NativePicker.folder(current: coordinator.outputDirectory, title: copy[.chooseFolder]) { coordinator.outputDirectory = folder }
                }.disabled(coordinator.isRunning)
                Button {
                    NSWorkspace.shared.open(coordinator.outputDirectory)
                } label: {
                    Text(coordinator.outputDirectory.path).lineLimit(1).truncationMode(.middle)
                        .foregroundStyle(.secondary).font(.caption)
                }
                .buttonStyle(.plain).help(copy[.openFolder] + "\n" + coordinator.outputDirectory.path)
                Spacer(minLength: 4)
                Button(copy[.cancelAll]) { coordinator.cancelAll() }.disabled(!coordinator.hasCancellableWork)
                Button { coordinator.startDownloads() } label: {
                    Label(copy[.download], systemImage: "arrow.down.to.line")
                }
                .buttonStyle(DownloadButtonStyle())
                .disabled(!canStart)
                .help(copy[.startHint])
            }
        }
    }

    private var statusAndLog: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 16) {
                Label("\(copy[.active]): \(coordinator.activeCount)/\(coordinator.maxConcurrentFiles)", systemImage: "arrow.down.circle.fill")
                    .foregroundStyle(coordinator.activeCount > 0 ? Color.blue : Color.secondary)
                Text("\(copy[.queued]): \(coordinator.queuedCount)")
                Text("\(copy[.completed]): \(coordinator.completedCount)")
                if coordinator.isInspecting {
                    HStack(spacing: 5) { ProgressView().controlSize(.mini); Text(copy[.checking]) }
                } else if coordinator.isAuthenticating {
                    HStack(spacing: 5) { ProgressView().controlSize(.mini); Text(copy[.authPreparing]) }
                }
                Spacer(minLength: 0)
                Text(queueSizeLabel).help(copy[.estimatesHint]).lineLimit(1)
            }
            .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
            HStack {
                Text(copy[.log]).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Spacer()
                Button(copy[.clearFinished]) { coordinator.clearFinished() }.buttonStyle(.link)
                    .font(.caption).disabled(coordinator.isRunning)
            }
            ScrollViewReader { proxy in
                GeometryReader { geometry in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(coordinator.logLines.isEmpty ? copy[.logEmpty] : coordinator.logLines.suffix(400).map(copy.logLine).joined(separator: "\n"))
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(coordinator.logLines.isEmpty ? Color.secondary : Color.primary)
                                .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                            Color.clear.frame(height: 1).id("log-tail")
                        }.padding(10)
                    }
                    .onChange(of: geometry.size) { _, _ in proxy.scrollTo("log-tail", anchor: .bottom) }
                }
                .frame(height: 104)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.secondary.opacity(0.18)))
                .onChange(of: coordinator.logLines.last) { _, _ in proxy.scrollTo("log-tail", anchor: .bottom) }
                .onAppear { proxy.scrollTo("log-tail", anchor: .bottom) }
            }
        }
    }

    private var queueSizeLabel: String {
        let size = coordinator.queueSize
        let known = size.knownBytes > 0 ? (size.approximate ? "≈ " : "") + AppCopy.bytes(size.knownBytes) : "—"
        let unknown = size.unknownCount > 0 ? " + \(size.unknownCount) \(copy[.unknown])" : ""
        return "\(copy[.queueSize]): \(known)\(unknown)"
    }

    private func fitWindowToScreen() {
        guard let window = NSApplication.shared.keyWindow ?? NSApplication.shared.mainWindow,
              let screen = window.screen ?? NSScreen.main else { return }
        let visible = screen.visibleFrame
        window.minSize = NSSize(width: min(900, visible.width), height: min(650, visible.height))
        let size = NSSize(width: min(1260, visible.width), height: min(800, visible.height))
        var frame = window.frame
        frame.size = size
        frame.origin.x = visible.midX - size.width / 2
        frame.origin.y = visible.midY - size.height / 2
        window.setFrame(frame, display: true, animate: false)
    }

    private func synchronizeSheet() {
        guard sheet == nil else { return }
        if coordinator.authPrompt != nil { sheet = .authorization }
        else if let group = coordinator.playlistGroups.first { sheet = .playlist(group.id) }
    }

    private func synchronizeAlert() {
        guard activeAlert == nil else { return }
        if let prompt = coordinator.overwritePrompt { activeAlert = .overwrite(prompt) }
        else if let summary = coordinator.batchSummary { activeAlert = .completion(summary) }
    }

    private func makeAlert(_ alert: AppAlert) -> Alert {
        switch alert {
        case .overwrite(let prompt):
            return Alert(title: Text(copy[.overwriteTitle]), message: Text(copy[.overwriteMessage] + "\n\n" + URL(fileURLWithPath: prompt.path).lastPathComponent), primaryButton: .destructive(Text(copy[.replace])) {
                answerOverwrite(prompt.taskID, overwrite: true)
            }, secondaryButton: .cancel(Text(copy[.skip])) {
                answerOverwrite(prompt.taskID, overwrite: false)
            })
        case .completion(let summary):
            var message = "\(copy[.completed]): \(summary.completed) · \(copy[.skipped]): \(summary.skipped)\n\(copy[.failed]): \(summary.failed) · \(copy[.cancelled]): \(summary.cancelled)"
            if summary.authenticationRequired > 0 {
                message += "\n\(copy[.authRequired]): \(summary.authenticationRequired)\n\n" + copy[.authNeededSummary]
            }
            message += "\n\n" + copy[.completionMessage]
            return Alert(title: Text(copy[.completionTitle]), message: Text(message), dismissButton: .default(Text(copy[.dismiss])) {
                coordinator.batchSummary = nil
                activeAlert = nil
            })
        }
    }

    private func answerOverwrite(_ id: UUID, overwrite: Bool) {
        activeAlert = nil
        coordinator.answerOverwrite(taskID: id, overwrite: overwrite)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { synchronizeAlert() }
    }
}
