import AppKit
import OpenMediaCore
import SwiftUI

enum AppMetadata {
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
}

@main
@MainActor
enum OpenMediaApplication {
    static func main() {
        let application = NSApplication.shared
        UserDefaults.standard.register(defaults: ["interfaceLanguage": InterfaceLanguage.german.rawValue, "interfaceAppearance": InterfaceAppearance.system.rawValue])
        application.setActivationPolicy(.regular)
        let delegate = ApplicationDelegate()
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}

@MainActor
private final class ApplicationDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let coordinator = DownloadCoordinator()
    private var window: NSWindow?
    private var closeApproved = false
    private var terminationPending = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Das Symbol aus diesem Build nutzen, nicht aus einem alten Dock-Cache.
        if let iconURL = Bundle.main.url(forResource: "AppIcon", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) {
            NSApplication.shared.applicationIconImage = icon
        }
        installMenu()
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1260, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "OpenMedia Downloader \(AppMetadata.version)"
        window.minSize = NSSize(width: 1120, height: 780)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = NSHostingView(rootView: MainView(coordinator: coordinator, languageChanged: { [weak self] in
            self?.installMenu()
        }))
        window.center()
        window.setFrameAutosaveName("OpenMediaDownloader55MainWindow")
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard confirmClose() else { return false }
        if coordinator.hasActiveWork {
            NSApplication.shared.terminate(nil)
            return false
        }
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard confirmClose() else { return .terminateCancel }
        guard coordinator.hasActiveWork else { return .terminateNow }
        guard !terminationPending else { return .terminateLater }
        terminationPending = true
        // Die Hauptschleife bleibt aktiv, bis auch die Kindprozesse beendet sind.
        Task { @MainActor [self] in
            let deadline = Date().addingTimeInterval(6)
            while coordinator.hasActiveWork && Date() < deadline {
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
            if coordinator.hasActiveWork {
                let language = InterfaceLanguage(rawValue: UserDefaults.standard.string(forKey: "interfaceLanguage") ?? "de") ?? .german
                let copy = AppCopy(language: language)
                let alert = NSAlert()
                alert.messageText = copy[.closeFailedTitle]
                alert.informativeText = "\(copy[.closeFailedMessage])\n\n\(copy[.recoveryFolder])\n\(coordinator.outputDirectory.path)"
                alert.addButton(withTitle: copy[.continueWaiting])
                alert.addButton(withTitle: copy[.closeAnyway])
                alert.buttons[1].hasDestructiveAction = true
                if alert.runModal() == .alertSecondButtonReturn {
                    coordinator.forceStopAll()
                    let forceDeadline = Date().addingTimeInterval(2.5)
                    while coordinator.hasActiveWork && Date() < forceDeadline {
                        try? await Task.sleep(nanoseconds: 50_000_000)
                    }
                    terminationPending = false
                    sender.reply(toApplicationShouldTerminate: true)
                    return
                }
                closeApproved = false
                window?.makeKeyAndOrderFront(nil)
                terminationPending = false
                sender.reply(toApplicationShouldTerminate: false)
                return
            }
            terminationPending = false
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { coordinator.shutdown() }

    private func confirmClose() -> Bool {
        guard !closeApproved else { return true }
        if coordinator.hasActiveWork {
            let language = InterfaceLanguage(rawValue: UserDefaults.standard.string(forKey: "interfaceLanguage") ?? "de") ?? .german
            let copy = AppCopy(language: language)
            let alert = NSAlert()
            alert.messageText = copy[.closeTitle]
            alert.informativeText = copy[.closeMessage]
            alert.alertStyle = .warning
            alert.addButton(withTitle: copy[.keepOpen])
            alert.addButton(withTitle: copy[.close])
            alert.buttons[1].hasDestructiveAction = true
            guard alert.runModal() == .alertSecondButtonReturn else { return false }
        }
        closeApproved = true
        coordinator.shutdown()
        return true
    }

    private func installMenu() {
        let language = InterfaceLanguage(rawValue: UserDefaults.standard.string(forKey: "interfaceLanguage") ?? "de") ?? .german
        let copy = AppCopy(language: language)
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: copy[.about], action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: copy[.quit], action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        menu.addItem(applicationItem)
        let editItem = NSMenuItem(title: copy[.edit], action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: copy[.edit])
        for command in EditCommand.allCases {
            let key: CopyKey
            let selector: Selector
            switch command {
            case .undo: key = .undo; selector = Selector(("undo:"))
            case .redo: key = .redo; selector = Selector(("redo:"))
            case .cut: key = .cut; selector = #selector(NSText.cut(_:))
            case .copy: key = .copy; selector = #selector(NSText.copy(_:))
            case .paste: key = .paste; selector = #selector(NSText.paste(_:))
            case .selectAll: key = .selectAllText; selector = #selector(NSText.selectAll(_:))
            }
            let item = editMenu.addItem(withTitle: copy[key], action: selector, keyEquivalent: command.keyEquivalent)
            item.keyEquivalentModifierMask = command.modifiers
        }
        editMenu.addItem(.separator())
        editMenu.addItem(preferenceMenuItem(
            title: copy[.language],
            options: InterfaceLanguage.allCases.map { ($0.name, $0.rawValue) },
            selectedValue: language.rawValue,
            action: #selector(changeInterfaceLanguage(_:))
        ))
        editMenu.addItem(preferenceMenuItem(
            title: copy[.appearance],
            options: [
                (copy[.systemAppearance], InterfaceAppearance.system.rawValue),
                (copy[.lightAppearance], InterfaceAppearance.light.rawValue),
                (copy[.darkAppearance], InterfaceAppearance.dark.rawValue)
            ],
            selectedValue: UserDefaults.standard.string(forKey: "interfaceAppearance") ?? InterfaceAppearance.system.rawValue,
            action: #selector(changeInterfaceAppearance(_:))
        ))
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApplication.shared.mainMenu = menu
    }

    private func preferenceMenuItem(
        title: String,
        options: [(String, String)],
        selectedValue: String,
        action: Selector
    ) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let submenu = NSMenu(title: title)
        for (label, value) in options {
            let option = NSMenuItem(title: label, action: action, keyEquivalent: "")
            option.target = self
            option.representedObject = value
            if value == selectedValue { option.state = .on }
            submenu.addItem(option)
        }
        item.submenu = submenu
        return item
    }

    @objc private func changeInterfaceLanguage(_ sender: NSMenuItem) {
        guard let value = sender.representedObject as? String,
              InterfaceLanguage(rawValue: value) != nil else { return }
        UserDefaults.standard.set(value, forKey: "interfaceLanguage")
        installMenu()
    }

    @objc private func changeInterfaceAppearance(_ sender: NSMenuItem) {
        guard let value = sender.representedObject as? String,
              InterfaceAppearance(rawValue: value) != nil else { return }
        UserDefaults.standard.set(value, forKey: "interfaceAppearance")
        installMenu()
    }
}
