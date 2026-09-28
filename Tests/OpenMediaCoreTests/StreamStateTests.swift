import Foundation
import Testing
@testable import OpenMediaCore

struct StreamStateTests {
    @Test func lifecycleStatesDecodeAndScheduledIsNotDownloadable() throws {
        for state in [StreamState.scheduled, .live, .endedProcessing, .vod, .regular] {
            let data = try JSONSerialization.data(withJSONObject: ["url": "https://example.invalid/x", "title": "x", "streamState": state.rawValue])
            #expect(try JSONDecoder().decode(MediaEntry.self, from: data).streamState == state)
        }
        #expect(!TaskStage.scheduled.isActive)
        #expect(TaskStage.endedProcessing.rawValue == "endedProcessing")
    }

    @Test func liveProgressCanRepresentElapsedBytesAndRateWithoutTotals() {
        var progress = DownloadProgress()
        progress.elapsedSeconds = 35
        progress.downloadedBytes = 4096
        progress.speedBytesPerSecond = 120
        #expect(progress.fraction == nil)
        #expect(progress.totalBytes == nil)
        #expect(progress.elapsedSeconds == 35)
    }
}
