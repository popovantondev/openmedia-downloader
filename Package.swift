// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "OpenMediaDownloader",
    defaultLocalization: "de",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "OpenMediaDownloader", targets: ["OpenMediaApp"])],
    targets: [
        .target(name: "OpenMediaCore"),
        .executableTarget(name: "OpenMediaApp", dependencies: ["OpenMediaCore"], exclude: ["Resources"]),
        .testTarget(name: "OpenMediaCoreTests", dependencies: ["OpenMediaCore"])
    ],
    swiftLanguageModes: [.v6]
)
