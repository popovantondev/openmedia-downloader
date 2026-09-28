import Foundation
import Testing
@testable import OpenMediaCore

struct PlaylistSheetTests {
    @Test func independentVariantsSurviveEntryMetadataReplacement() {
        let discovered = MediaEntry(url: "https://example.org/video/1", title: "One", availability: .unknown)
        let selections = [
            PlaylistSelection(entryID: discovered.id, media: .video, quality: "720"),
            PlaylistSelection(entryID: discovered.id, media: .aac, quality: "best")
        ]
        let detailed = MediaEntry(url: discovered.url, title: "One detailed", availableHeights: [720], availability: .available, estimates: [
            SizeEstimate(media: .video, quality: "720", bytes: 1000, approximate: true)
        ])

        #expect(selections.map(\.id).count == Set(selections.map(\.id)).count)
        #expect(selections.allSatisfy { $0.entryID == detailed.id })
        #expect(selections.map(\.media) == [.video, .aac])
        #expect(selections.map(\.quality) == ["720", "best"])
        #expect(detailed.estimates.first?.approximate == true)
        #expect(detailed.estimates.first(where: { $0.media == .aac }) == nil)
    }
}
