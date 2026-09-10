import XCTest
@testable import Surgebar

final class ElsewhereAcceptanceTests: XCTestCase {
    @MainActor func testInstalledCLIReadOnlyJourney() async throws {
        guard ProcessInfo.processInfo.environment["SURGEBAR_LIVE_READ"] == "1" else { throw XCTSkip("Opt-in installed-runtime read-only acceptance") }
        let model = ElsewhereModel()
        await model.refresh()
        XCTAssertNil(model.error, model.error ?? "")
        XCTAssertNotNil(model.updated)
        XCTAssertNotNil(model.queue["capacity"]["memory"]["memory_level"].number)
        XCTAssertFalse(model.providers["providers"].object.isEmpty)
        XCTAssertNotNil(model.configURL)
        XCTAssertTrue(model.version.hasPrefix("elsewhere "))
    }

}
