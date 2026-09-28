import AppKit
import SwiftUI

/// Column widths shared by queue headings and rows so controls remain aligned
/// while the queue's single horizontal scroll view moves both together.
/// AppKit scrollbar placement and SwiftUI truncation/hover appearance still need
/// visual QA at multiple window sizes; the core test target cannot host app UI.
enum QueueColumnMetrics {
    static let spacing: CGFloat = 10
    static let titleMinimum: CGFloat = 260
    static let format: CGFloat = 102
    static let quality: CGFloat = 107
    static let mode: CGFloat = 95
    static let size: CGFloat = 92
    static let progress: CGFloat = 238
    static let action: CGFloat = 29
    static let horizontalInset: CGFloat = 12
    static let scrollbarInset: CGFloat = 15
    static let minimumTableWidth: CGFloat = 1150
}

// A wrapped URL editor scrolls vertically only, including automatic cursor scrolling.
@MainActor
private final class LinkClipView: NSClipView {
    override func constrainBoundsRect(_ proposedBounds: NSRect) -> NSRect {
        var bounds = super.constrainBoundsRect(proposedBounds)
        bounds.origin.x = 0
        return bounds
    }
}

@MainActor
private final class LinkScrollView: NSScrollView {
    override func tile() {
        super.tile()
        guard let editor = documentView as? NSTextView else { return }
        let width = contentSize.width
        if width > 0, editor.frame.width != width {
            editor.setFrameSize(NSSize(width: width, height: max(editor.frame.height, contentSize.height)))
        }
        if contentView.bounds.origin.x != 0 {
            contentView.scroll(to: NSPoint(x: 0, y: contentView.bounds.origin.y))
        }
    }
}

@MainActor
private final class LinkTextView: NSTextView {
    override func paste(_ sender: Any?) {
        super.paste(sender)
        let cursor = selectedRange().location
        let text = string as NSString
        if cursor > 0, cursor <= text.length, text.substring(with: NSRange(location: cursor - 1, length: 1)) != "\n" {
            insertText("\n", replacementRange: selectedRange())
        }
    }
}

@MainActor
struct LinkEditor: NSViewRepresentable {
    @Binding var text: String
    let label: String
    let help: String
    let onEdit: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = LinkScrollView()
        scroll.contentView = LinkClipView()
        scroll.hasHorizontalScroller = false
        scroll.horizontalScrollElasticity = .none
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = false
        scroll.borderType = .noBorder
        scroll.drawsBackground = false
        let editor = LinkTextView(frame: NSRect(x: 0, y: 0, width: 700, height: 90))
        editor.delegate = context.coordinator
        editor.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        editor.textColor = .labelColor
        editor.insertionPointColor = .systemBlue
        editor.isRichText = false
        editor.isAutomaticQuoteSubstitutionEnabled = false
        editor.isAutomaticDashSubstitutionEnabled = false
        editor.isAutomaticLinkDetectionEnabled = false
        editor.isAutomaticSpellingCorrectionEnabled = false
        editor.isContinuousSpellCheckingEnabled = false
        editor.allowsUndo = true
        editor.drawsBackground = false
        editor.isVerticallyResizable = true
        editor.isHorizontallyResizable = false
        editor.autoresizingMask = [.width]
        editor.textContainer?.widthTracksTextView = true
        editor.textContainer?.containerSize = NSSize(width: 700, height: CGFloat.greatestFiniteMagnitude)
        editor.textContainerInset = NSSize(width: 7, height: 8)
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byCharWrapping
        editor.defaultParagraphStyle = paragraph
        editor.minSize = NSSize(width: 0, height: 90)
        editor.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        editor.string = text
        editor.setAccessibilityLabel(label)
        editor.setAccessibilityHelp(help)
        scroll.documentView = editor
        DispatchQueue.main.async { [weak editor] in
            if let editor { editor.window?.makeFirstResponder(editor) }
        }
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard let editor = scroll.documentView as? LinkTextView else { return }
        editor.setAccessibilityLabel(label)
        editor.setAccessibilityHelp(help)
        if editor.string != text { editor.string = text }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: LinkEditor
        init(_ parent: LinkEditor) { self.parent = parent }
        func textDidChange(_ notification: Notification) {
            guard let editor = notification.object as? NSTextView else { return }
            parent.text = editor.string
            parent.onEdit(editor.string)
        }
    }
}

@MainActor
enum NativePicker {
    static func folder(current: URL, title: String) -> URL? {
        let panel = NSOpenPanel()
        panel.title = title
        panel.directoryURL = current
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        return panel.runModal() == .OK ? panel.url : nil
    }

    static func cookies(title: String) -> URL? {
        let panel = NSOpenPanel()
        panel.title = title
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        return panel.runModal() == .OK ? panel.url : nil
    }
}

struct DownloadButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(.white.opacity(enabled ? 1 : 0.65))
            .frame(minWidth: 205, minHeight: 43)
            .padding(.horizontal, 15)
            .background(configuration.isPressed ? Color(red: 0.34, green: 0.45, blue: 0.59) : Color.blue.opacity(enabled ? 1 : 0.40))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.white.opacity(0.12), lineWidth: 1))
    }
}

struct SquareSymbolButton: View {
    let symbol: String
    let help: String
    var destructive = false
    let action: () -> Void
    @State private var hovering = false
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .frame(width: QueueColumnMetrics.action, height: QueueColumnMetrics.action, alignment: .center)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(hovering && destructive ? Color.red : Color.secondary)
        .background(hovering ? (destructive ? Color.red : Color.blue).opacity(0.10) : Color.clear)
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(hovering && destructive ? Color.red : Color.secondary.opacity(0.5), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .opacity(enabled ? 1 : 0.5)
        .onHover { hovering = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}
