import Foundation
import Security

public enum KeychainError: Error, LocalizedError {
    case unexpectedStatus(OSStatus)

    public var errorDescription: String? {
        switch self {
        case let .unexpectedStatus(status):
            return "Keychain operation failed with status \(status)."
        }
    }
}

/// The small surface the session store needs from secure storage. Tests and
/// previews can replace it with an in-memory implementation.
public protocol KeychainStoring {
    func readToken() -> String?
    func saveToken(_ token: String) throws
    func deleteToken()
}

public struct KeychainStore: KeychainStoring {
    public let service: String
    public let account: String

    public init(
        service: String = Bundle.main.bundleIdentifier ?? "com.example.app",
        account: String = "session-token"
    ) {
        self.service = service
        self.account = account
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    public func readToken() -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data,
              let token = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return token
    }

    public func saveToken(_ token: String) throws {
        guard let data = token.data(using: .utf8) else {
            throw KeychainError.unexpectedStatus(errSecParam)
        }

        let attributes = [kSecValueData as String: data] as CFDictionary
        let updateStatus = SecItemUpdate(baseQuery as CFDictionary, attributes)
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw KeychainError.unexpectedStatus(updateStatus)
        }

        var insert = baseQuery
        insert[kSecValueData as String] = data
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(insert as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw KeychainError.unexpectedStatus(addStatus)
        }
    }

    public func deleteToken() {
        SecItemDelete(baseQuery as CFDictionary)
    }
}
