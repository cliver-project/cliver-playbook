import XCTest
@testable import Core

/// Opt-in check that the generated client and the running API agree.
///
/// Set `CLIVER_LIVE_API_URL` (for example `http://127.0.0.1:8000/api/v1`)
/// and start the API before running the suite. The test registers a fresh
/// user, so it never depends on seeded credentials.
final class LiveContractTests: XCTestCase {
    func testRegisterMeAndProductsAgainstLiveAPI() async throws {
        guard let raw = ProcessInfo.processInfo.environment["CLIVER_LIVE_API_URL"],
              let baseURL = URL(string: raw) else {
            throw XCTSkip("Set CLIVER_LIVE_API_URL to run this test.")
        }
        let client = APIClient(baseURL: baseURL)
        defer { client.setToken(nil) }

        let username = "live.\(UUID().uuidString.prefix(12).lowercased())"
        let session = try await client.register(
            username: username,
            password: "LiveContract!2345",
            email: nil,
            displayName: "Live Contract"
        )
        XCTAssertFalse(session.token.isEmpty)
        XCTAssertEqual(session.user.username, username)

        client.setToken(session.token)
        let me = try await client.me()
        XCTAssertEqual(me.username, username)
        XCTAssertEqual(me.displayName, "Live Contract")

        let created = try await client.createProduct(
            name: "Live contract \(username)",
            description: "",
            priceCents: 123
        )
        let products = try await client.products()
        XCTAssertTrue(products.contains { $0.id == created.id })
        try await client.deleteProduct(id: created.id)
    }
}
