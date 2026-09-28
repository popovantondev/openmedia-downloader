import AVFoundation
import CoreVideo
import Foundation

func fail(_ message: String) -> Never {
    fputs("Fixture generation failed: \(message)\n", stderr)
    exit(1)
}

guard CommandLine.arguments.count == 2 else { fail("expected output path") }
let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])
try? FileManager.default.removeItem(at: outputURL)

let width = 160
let height = 90
let writer: AVAssetWriter
do { writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4) }
catch { fail(error.localizedDescription) }
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height
])
input.expectsMediaDataInRealTime = false
let attributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
]
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: attributes)
guard writer.canAdd(input) else { fail("H.264 input is unavailable") }
writer.add(input)
guard writer.startWriting() else { fail(writer.error?.localizedDescription ?? "writer did not start") }
writer.startSession(atSourceTime: .zero)
guard let pool = adaptor.pixelBufferPool else { fail("pixel buffer pool is unavailable") }

for frame in 0..<180 {
    while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.005) }
    var optionalBuffer: CVPixelBuffer?
    guard CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &optionalBuffer) == kCVReturnSuccess,
          let buffer = optionalBuffer else { fail("could not allocate video frame") }
    CVPixelBufferLockBaseAddress(buffer, [])
    if let base = CVPixelBufferGetBaseAddress(buffer) {
        let bytes = base.assumingMemoryBound(to: UInt8.self)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        for y in 0..<height {
            for x in 0..<width {
                let offset = y * rowBytes + x * 4
                bytes[offset] = UInt8((x + frame * 3) % 256)
                bytes[offset + 1] = UInt8((y * 2 + frame * 5) % 256)
                bytes[offset + 2] = UInt8((x + y + frame * 7) % 256)
                bytes[offset + 3] = 255
            }
        }
    }
    CVPixelBufferUnlockBaseAddress(buffer, [])
    guard adaptor.append(buffer, withPresentationTime: CMTime(value: Int64(frame), timescale: 30)) else {
        fail(writer.error?.localizedDescription ?? "could not append video frame")
    }
}

input.markAsFinished()
let finished = DispatchSemaphore(value: 0)
writer.finishWriting { finished.signal() }
guard finished.wait(timeout: .now() + 20) == .success, writer.status == .completed else {
    fail(writer.error?.localizedDescription ?? "writer did not finish")
}
