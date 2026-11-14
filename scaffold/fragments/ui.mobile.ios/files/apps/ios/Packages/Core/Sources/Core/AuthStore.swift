import Foundation
import Observation

/// Owns the session: the bearer token (persisted in the Keychain) and the
/// signed-in user. A 401 from an authenticated request clears both and returns
/// the UI to sign-in.
@MainActor
@Observable
public final class AuthStore {
    public private(set) var user: User?
    public private(set) var token: String?
    public private(set) var isRestoring = true

    public let api: APIClient
    private let keychain: KeychainStoring

    public var isAuthenticated: Bool {
        user != nil && token != nil
    }

    public init(
        api: APIClient = APIClient(),
        keychain: KeychainStoring = KeychainStore()
    ) {
        self.api = api
        self.keychain = keychain
        api.setUnauthorizedHandler { [weak self] in
            await self?.handleUnauthorized()
        }
    }

    /// Reads the persisted token and verifies it with `GET /auth/me`.
    /// A transport failure leaves the token in place for a later launch;
    /// only a 401 clears it.
    public func restoreSession() async {
        defer { isRestoring = false }
        guard let stored = keychain.readToken(), !stored.isEmpty else {
            return
        }
        token = stored
        api.setToken(stored)
        do {
            user = try await api.me()
        } catch APIError.unauthorized {
            clearSession()
        } catch is CancellationError {
            // A cancelled task says nothing about the session.
        } catch {
            // Offline or server unavailable: keep the token, show sign-in.
            user = nil
        }
    }

    public func signIn(username: String, password: String) async throws {
        let session = try await api.login(username: username, password: password)
        apply(session)
    }

    public func register(
        username: String,
        password: String,
        email: String?,
        displayName: String?
    ) async throws {
        let session = try await api.register(
            username: username,
            password: password,
            email: email,
            displayName: displayName
        )
        apply(session)
    }

    public func updateProfile(
        email: String?,
        phone: String?,
        displayName: String?
    ) async throws {
        user = try await api.updateProfile(
            email: email,
            phone: phone,
            displayName: displayName
        )
    }

    public func signOut() {
        clearSession()
    }

    private func apply(_ session: AuthSession) {
        token = session.token
        user = session.user
        api.setToken(session.token)
        do {
            try keychain.saveToken(session.token)
        } catch {
            // The in-memory session is still valid for this launch; the next
            // launch simply asks the user to sign in again.
        }
    }

    private func handleUnauthorized() {
        clearSession()
    }

    private func clearSession() {
        api.setToken(nil)
        keychain.deleteToken()
        token = nil
        user = nil
    }
}
