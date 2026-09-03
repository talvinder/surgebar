// swift-tools-version: 5.9
import PackageDescription

// surgebar — native macOS menu-bar monitor for CPU + memory pressure.
// A resource monitor should be nearly invisible in the resources it uses;
// this replaces the Python prototype (kept as the reference implementation).
let package = Package(
    name: "Surgebar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Surgebar",
            path: "Sources/Surgebar"
        ),
    ]
)
