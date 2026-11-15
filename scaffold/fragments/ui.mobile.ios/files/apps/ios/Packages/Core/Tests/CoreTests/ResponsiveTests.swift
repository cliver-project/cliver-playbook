import SwiftUI
import XCTest
@testable import Core

final class ResponsiveTests: XCTestCase {
    func testLayoutModeUsesRegularOnlyForRegularWidth() {
        XCTAssertEqual(LayoutMode(sizeClass: .compact), .compact)
        XCTAssertEqual(LayoutMode(sizeClass: .regular), .regular)
        XCTAssertEqual(LayoutMode(sizeClass: nil), .compact)
    }
}
