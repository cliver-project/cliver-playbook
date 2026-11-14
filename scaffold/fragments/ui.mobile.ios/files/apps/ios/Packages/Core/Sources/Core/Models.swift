import Foundation

// Wire models for the API contract. Coding keys are explicit so the Swift
// names stay idiomatic while the JSON stays snake_case.

public struct User: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let username: String
    public let email: String?
    public let phone: String?
    public let displayName: String
    public let isActive: Bool
    public let mustChangePassword: Bool
    public let createdAt: String
    public let roleCodes: [String]
    public let permissions: [String]

    public init(
        id: Int,
        username: String,
        email: String?,
        phone: String?,
        displayName: String,
        isActive: Bool,
        mustChangePassword: Bool,
        createdAt: String,
        roleCodes: [String],
        permissions: [String]
    ) {
        self.id = id
        self.username = username
        self.email = email
        self.phone = phone
        self.displayName = displayName
        self.isActive = isActive
        self.mustChangePassword = mustChangePassword
        self.createdAt = createdAt
        self.roleCodes = roleCodes
        self.permissions = permissions
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case username
        case email
        case phone
        case displayName = "display_name"
        case isActive = "is_active"
        case mustChangePassword = "must_change_password"
        case createdAt = "created_at"
        case roleCodes = "role_codes"
        case permissions
    }
}

public struct AuthSession: Codable, Equatable, Sendable {
    public let token: String
    public let mustChangePassword: Bool
    public let user: User

    public init(token: String, mustChangePassword: Bool, user: User) {
        self.token = token
        self.mustChangePassword = mustChangePassword
        self.user = user
    }

    private enum CodingKeys: String, CodingKey {
        case token
        case mustChangePassword = "must_change_password"
        case user
    }
}

public struct MeResponse: Codable, Equatable, Sendable {
    public let user: User

    public init(user: User) {
        self.user = user
    }
}

public struct Product: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public var name: String
    public var description: String
    public var priceCents: Int
    public let createdAt: String
    public let updatedAt: String

    public init(
        id: Int,
        name: String,
        description: String,
        priceCents: Int,
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.name = name
        self.description = description
        self.priceCents = priceCents
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case description
        case priceCents = "price_cents"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

// Request bodies. Optional fields are omitted from the payload when nil, which
// lets PATCH requests send only the values the user changed.

struct LoginRequest: Encodable {
    let username: String
    let password: String
}

struct RegisterRequest: Encodable {
    let username: String
    let password: String
    let email: String?
    let displayName: String?

    private enum CodingKeys: String, CodingKey {
        case username
        case password
        case email
        case displayName = "display_name"
    }
}

struct ProfileUpdateRequest: Encodable {
    let email: String?
    let phone: String?
    let displayName: String?

    private enum CodingKeys: String, CodingKey {
        case email
        case phone
        case displayName = "display_name"
    }
}

struct ProductCreateRequest: Encodable {
    let name: String
    let description: String
    let priceCents: Int

    private enum CodingKeys: String, CodingKey {
        case name
        case description
        case priceCents = "price_cents"
    }
}

struct ProductUpdateRequest: Encodable {
    let name: String
    let description: String
    let priceCents: Int

    private enum CodingKeys: String, CodingKey {
        case name
        case description
        case priceCents = "price_cents"
    }
}
