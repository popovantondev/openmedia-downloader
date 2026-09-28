import Foundation
import Testing
@testable import OpenMediaCore

struct MediaSourceTests {
    @Test func classifiesSingleVideo() throws {
        let source = try #require(MediaSource(string: "https://www.youtube.com/watch?v=abc"))
        #expect(source.kind == .video)
    }

    @Test func watchAndListOffersBothChoices() throws {
        let source = try #require(MediaSource(string: "https://www.youtube.com/watch?v=abc&list=PL123"))
        #expect(source.kind == .videoAndPlaylist)
        #expect(source.arguments(for: .video) == ["--no-playlist"])
        #expect(source.arguments(for: .playlist).isEmpty)
    }

    @Test func keepsVimeoUnlistedHash() throws {
        let source = try #require(MediaSource(string: "https://vimeo.com/123456?h=secret"))
        #expect(source.kind == .video)
        #expect(source.url.absoluteString == "https://vimeo.com/123456?h=secret")
    }

    @Test func classifiesOrdinaryPlaylist() throws {
        let source = try #require(MediaSource(string: "https://www.youtube.com/playlist?list=PL123"))
        #expect(source.kind == .playlist)
    }

    @Test func rejectsNonHTTPAndUsesSupportedNoPlaylistSwitchForVideo() throws {
        #expect(MediaSource(string: "file:///tmp/video") == nil)
        let source = try #require(MediaSource(string: "https://example.org/video"))
        #expect(source.arguments(for: .video) == ["--no-playlist"])
    }
}
