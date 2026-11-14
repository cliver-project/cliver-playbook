// swift-tools-version: 5.9
import PackageDescription

// macOS is listed so the package tests can run on a Mac without a simulator.
// The app target itself is iOS only.
let package = Package(
    name: "Core",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "Core", targets: ["Core"]),
    ],
    targets: [
        .target(name: "Core", path: "Sources/Core"),
        .testTarget(name: "CoreTests", dependencies: ["Core"], path: "Tests/CoreTests"),
    ]
)
