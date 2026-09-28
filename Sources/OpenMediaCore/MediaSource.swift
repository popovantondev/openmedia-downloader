import Foundation

/// The URL shape tells the caller what choices to offer; the original URL is
/// retained so service parameters (including Vimeo's unlisted `h` value) survive.
public struct MediaSource: Equatable, Sendable {
    public enum Kind: String, Codable, Sendable { case video, videoAndPlaylist, playlist }
    public enum Choice: String, Codable, Sendable { case video, playlist }

    public let url: URL
    public let kind: Kind

    public init?(url: URL) {
        guard let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host?.lowercased() else { return nil }
        self.url = url
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let isYouTubeWatch = (host == "youtube.com" || host == "www.youtube.com" || host == "m.youtube.com")
            && url.path == "/watch"
        let hasVideo = isYouTubeWatch && query.contains { $0.name == "v" && !($0.value ?? "").isEmpty }
        let hasList = query.contains { $0.name == "list" && !($0.value ?? "").isEmpty }
        if hasVideo && hasList { kind = .videoAndPlaylist }
        else if hasVideo || Self.isVimeoVideo(host: host, path: url.path) { kind = .video }
        else if hasList || Self.isPlaylistPath(host: host, path: url.path) { kind = .playlist }
        else { kind = .video }
    }

    public init?(string: String) { guard let url = URL(string: string) else { return nil }; self.init(url: url) }

    /// Explicit choice controls yt-dlp playlist expansion. Service query values
    /// remain untouched on the URL passed to both inspection and download.
    public func arguments(for choice: Choice) -> [String] {
        choice == .video ? ["--no-playlist"] : []
    }

    private static func isVimeoVideo(host: String, path: String) -> Bool {
        (host == "vimeo.com" || host.hasSuffix(".vimeo.com")) &&
            path.split(separator: "/").contains { Int($0) != nil }
    }
    private static func isPlaylistPath(host: String, path: String) -> Bool {
        (host.contains("youtube.com") && path == "/playlist") ||
            (host == "vimeo.com" || host.hasSuffix(".vimeo.com")) && path.contains("/showcase/")
    }
}
