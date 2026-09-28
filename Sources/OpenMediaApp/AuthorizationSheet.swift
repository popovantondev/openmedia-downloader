import OpenMediaCore
import SwiftUI

struct AuthorizationSheet: View {
    @ObservedObject var coordinator: DownloadCoordinator
    let copy: AppCopy
    let dismiss: () -> Void
    @State private var method = "public"
    @State private var browser = "safari"
    @State private var cookieFile: URL?
    @State private var allowedDomains = Set<String>()

    private var canPrepare: Bool { method != "file" || cookieFile != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 13) {
                Image(systemName: "lock.shield").font(.system(size: 31)).foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 4) {
                    Text(copy[.authTitle]).font(.title2.bold())
                    Text(copy[.authOnce]).font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Text(copy[.authExplanation]).fixedSize(horizontal: false, vertical: true)
            Picker(copy[.authorization], selection: $method) {
                Text(copy[.authPublic]).tag("public")
                Text(copy[.authBrowser]).tag("browser")
                Text(copy[.authFile]).tag("file")
            }
            .pickerStyle(.radioGroup)
            .disabled(coordinator.isAuthenticating)
            .accessibilityIdentifier("authorization-method")

            if method == "browser" {
                HStack {
                    Text(copy[.browser])
                    Picker(copy[.browser], selection: $browser) {
                        Text("Safari").tag("safari")
                        Text("Chrome").tag("chrome")
                        Text("Opera").tag("opera")
                        Text("Firefox").tag("firefox")
                        Text("Edge").tag("edge")
                        Text("Brave").tag("brave")
                    }.labelsHidden().frame(width: 185)
                        .disabled(coordinator.isAuthenticating)
                        .accessibilityIdentifier("authorization-browser")
                }
                if browser != "firefox" {
                    Label(copy[browser == "safari" ? .authSafari : .authKeychain], systemImage: "info.circle")
                        .font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(copy[.authBrowserClosed])
                    .font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if method == "file" {
                HStack {
                    Button(copy[.chooseCookies]) { cookieFile = NativePicker.cookies(title: copy[.chooseCookies]) }
                        .disabled(coordinator.isAuthenticating)
                    Text(cookieFile?.lastPathComponent ?? copy[.noCookiesFile])
                        .lineLimit(1).truncationMode(.middle).foregroundStyle(.secondary)
                }
            }
            if method != "public", !coordinator.additionalAuthDomains.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    Text(copy[.authDomainTitle]).font(.headline)
                    Text(copy[.authDomainConsent]).font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    ScrollView {
                        VStack(alignment: .leading, spacing: 5) {
                            ForEach(coordinator.additionalAuthDomains, id: \.self) { domain in
                                Toggle(domain, isOn: Binding(
                                    get: { allowedDomains.contains(domain) },
                                    set: { isAllowed in
                                        if isAllowed { allowedDomains.insert(domain) }
                                        else { allowedDomains.remove(domain) }
                                    }
                                ))
                                .toggleStyle(.checkbox)
                            }
                        }
                    }
                    .frame(maxHeight: 140)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
            }
            if coordinator.authenticationStatus == "ready" {
                Label(copy[.authReadable], systemImage: "checkmark.shield")
                    .font(.callout).foregroundStyle(.green)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let prompt = coordinator.authPrompt, prompt.errorCode != nil {
                VStack(alignment: .leading, spacing: 5) {
                    Label(copy[.authError], systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(copy.authenticationError(code: prompt.errorCode, fallback: prompt.message))
                        .font(.callout).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(.orange.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
            }
            Label(copy[.authPrivacy], systemImage: "externaldrive.badge.checkmark")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Divider()
            HStack {
                // Abbrechen bleibt während der Prüfung erreichbar.
                Button(copy[.cancel]) { coordinator.cancelAuthentication(); dismiss() }
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("authorization-cancel")
                Spacer()
                if coordinator.isAuthenticating {
                    ProgressView().controlSize(.small)
                    Text(copy[.authPreparing]).foregroundStyle(.secondary)
                } else {
                    if method != "public" {
                        Button(copy[.continuePublic]) { coordinator.resolveAuthentication(.anonymous) }
                    }
                    Button(method == "public" ? copy[.continuePublic] : copy[.checkCookies]) { prepare() }
                        .buttonStyle(.borderedProminent)
                        .disabled(!canPrepare)
                        .keyboardShortcut(.defaultAction)
                        .accessibilityIdentifier("authorization-prepare")
                }
            }
        }
        .padding(26)
        .frame(width: 610)
        .interactiveDismissDisabled(coordinator.isAuthenticating)
    }

    private func prepare() {
        switch method {
        case "browser": coordinator.resolveAuthentication(.browser(browser), allowedDomains: Array(allowedDomains))
        case "file": if let cookieFile { coordinator.resolveAuthentication(.cookiesFile(cookieFile), allowedDomains: Array(allowedDomains)) }
        default: coordinator.resolveAuthentication(.anonymous)
        }
    }
}
