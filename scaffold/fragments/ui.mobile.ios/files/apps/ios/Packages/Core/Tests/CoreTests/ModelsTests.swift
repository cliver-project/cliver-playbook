import XCTest
@testable import Core

final class ModelsTests: XCTestCase {
    func testDecodesLoginSessionAndSnakeCaseUser() throws {
        let json = """
        {
          "token": "session-token",
          "must_change_password": false,
          "user": {
            "id": 7,
            "username": "ada",
            "email": "ada@example.test",
            "phone": null,
            "display_name": "Ada Lovelace",
            "is_active": true,
            "must_change_password": false,
            "created_at": "2026-01-02T03:04:05Z",
            "role_codes": ["admin", "member"],
            "permissions": ["products.read", "products.write"]
          }
        }
        """

        let session = try JSONDecoder().decode(
            AuthSession.self,
            from: Data(json.utf8)
        )

        XCTAssertEqual(session.token, "session-token")
        XCTAssertFalse(session.mustChangePassword)
        XCTAssertEqual(session.user.id, 7)
        XCTAssertEqual(session.user.username, "ada")
        XCTAssertEqual(session.user.displayName, "Ada Lovelace")
        XCTAssertEqual(session.user.email, "ada@example.test")
        XCTAssertNil(session.user.phone)
        XCTAssertTrue(session.user.isActive)
        XCTAssertEqual(session.user.roleCodes, ["admin", "member"])
        XCTAssertEqual(session.user.permissions, ["products.read", "products.write"])
        XCTAssertEqual(session.user.createdAt, "2026-01-02T03:04:05Z")
    }

    func testDecodesProduct() throws {
        let json = """
        {
          "id": 3,
          "name": "Reference widget",
          "description": "Replace with the project's domain.",
          "price_cents": 1999,
          "created_at": "2026-01-02T03:04:05Z",
          "updated_at": "2026-01-03T04:05:06Z"
        }
        """

        let product = try JSONDecoder().decode(Product.self, from: Data(json.utf8))

        XCTAssertEqual(product.id, 3)
        XCTAssertEqual(product.name, "Reference widget")
        XCTAssertEqual(product.description, "Replace with the project's domain.")
        XCTAssertEqual(product.priceCents, 1999)
        XCTAssertEqual(product.updatedAt, "2026-01-03T04:05:06Z")
    }

    func testDefaultBaseURLIsTheDocumentedLocalDevelopmentURL() {
        XCTAssertEqual(
            APIClient.defaultBaseURL.absoluteString,
            "http://127.0.0.1:8000/api/v1"
        )
        XCTAssertEqual(
            APIClient.configuredBaseURL(bundle: Bundle(for: ModelsTests.self)),
            APIClient.defaultBaseURL
        )
    }
}
