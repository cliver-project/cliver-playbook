import Core
import XCTest

final class AppTests: XCTestCase {
    func testBaseURLDefaultsToTheDocumentedLocalDevelopmentURL() {
        XCTAssertEqual(
            APIClient.defaultBaseURL.absoluteString,
            "http://127.0.0.1:8000/api/v1"
        )
    }
}
