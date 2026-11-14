import Foundation

public enum APIError: Error, LocalizedError {
    case invalidURL
    case invalidResponse
    case unauthorized
    case http(status: Int, message: String)
    case decoding(Error)
    case transport(Error)

    public var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "The API base URL is invalid."
        case .invalidResponse:
            return "The server returned an invalid response."
        case .unauthorized:
            return "Your session expired. Sign in again to continue."
        case let .http(status, message):
            return "Request failed (\(status)): \(message)"
        case let .decoding(error):
            return "The server response could not be read: \(error.localizedDescription)"
        case let .transport(error):
            return error.localizedDescription
        }
    }
}

/// HTTP client for the project's API. The base URL comes from the
/// `API_BASE_URL` Info.plist key and falls back to the documented local
/// development default.
public final class APIClient: @unchecked Sendable {
    /// The documented local development default. Change it in Info.plist for
    /// every other environment; no other host is known to the scaffold.
    public static let defaultBaseURL = URL(string: "http://127.0.0.1:8000/api/v1")!

    public let baseURL: URL

    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private let lock = NSLock()
    private var token: String?
    private var unauthorizedHandler: (@Sendable () async -> Void)?

    public init(baseURL: URL? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL ?? APIClient.configuredBaseURL()
        self.session = session
    }

    public static func configuredBaseURL(
        bundle: Bundle = .main,
        key: String = "API_BASE_URL"
    ) -> URL {
        if let raw = bundle.object(forInfoDictionaryKey: key) as? String,
           let url = URL(string: raw),
           !raw.isEmpty {
            return url
        }
        return defaultBaseURL
    }

    /// Sets the bearer token used for authenticated requests.
    public func setToken(_ token: String?) {
        lock.lock()
        defer { lock.unlock() }
        self.token = token
    }

    /// Called exactly once per authenticated 401 response, after the client
    /// has dropped its in-memory token. The session store uses it to clear
    /// persisted credentials and return to sign-in.
    public func setUnauthorizedHandler(_ handler: (@Sendable () async -> Void)?) {
        lock.lock()
        defer { lock.unlock() }
        unauthorizedHandler = handler
    }

    // MARK: - Auth

    public func login(username: String, password: String) async throws -> AuthSession {
        try await request(
            "POST",
            path: "/auth/login",
            body: LoginRequest(username: username, password: password),
            authenticated: false
        )
    }

    public func register(
        username: String,
        password: String,
        email: String?,
        displayName: String?
    ) async throws -> AuthSession {
        try await request(
            "POST",
            path: "/auth/register",
            body: RegisterRequest(
                username: username,
                password: password,
                email: email,
                displayName: displayName
            ),
            authenticated: false
        )
    }

    public func me() async throws -> User {
        let response: MeResponse = try await request("GET", path: "/auth/me")
        return response.user
    }

    public func updateProfile(
        email: String?,
        phone: String?,
        displayName: String?
    ) async throws -> User {
        let response: MeResponse = try await request(
            "PATCH",
            path: "/auth/profile",
            body: ProfileUpdateRequest(
                email: email,
                phone: phone,
                displayName: displayName
            )
        )
        return response.user
    }

    // MARK: - Products

    public func products(limit: Int = 50, offset: Int = 0) async throws -> [Product] {
        try await request(
            "GET",
            path: "/products",
            query: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset)),
            ]
        )
    }

    public func product(id: Int) async throws -> Product {
        try await request("GET", path: "/products/\(id)")
    }

    public func createProduct(
        name: String,
        description: String,
        priceCents: Int
    ) async throws -> Product {
        try await request(
            "POST",
            path: "/products",
            body: ProductCreateRequest(
                name: name,
                description: description,
                priceCents: priceCents
            )
        )
    }

    public func updateProduct(
        id: Int,
        name: String,
        description: String,
        priceCents: Int
    ) async throws -> Product {
        try await request(
            "PATCH",
            path: "/products/\(id)",
            body: ProductUpdateRequest(
                name: name,
                description: description,
                priceCents: priceCents
            )
        )
    }

    public func deleteProduct(id: Int) async throws {
        _ = try await send("DELETE", path: "/products/\(id)")
    }

    // MARK: - Agent runs

    /// Start a coordinator run and return its id.
    public func startAgentRun(message: String) async throws -> String {
        struct Body: Encodable {
            let message: String
        }
        struct Created: Decodable {
            let runID: String

            private enum CodingKeys: String, CodingKey {
                case runID = "run_id"
            }
        }
        let created: Created = try await request(
            "POST",
            path: "/agent/runs",
            body: Body(message: message)
        )
        return created.runID
    }

    /// Ask the API to cancel a run. Best-effort from the chat surface.
    public func cancelAgentRun(runID: String) async throws {
        _ = try await send("POST", path: "/agent/runs/\(runID)/cancel")
    }

    /// Attach the user's outcome rating to one completed run.
    public func submitAgentFeedback(
        runID: String,
        agent: String,
        rating: Int,
        comment: String = ""
    ) async throws {
        struct Body: Encodable {
            let agent: String
            let rating: Int
            let comment: String
        }
        _ = try await send(
            "POST",
            path: "/agent/runs/\(runID)/feedback",
            body: Body(agent: agent, rating: rating, comment: comment)
        )
    }

    /// Stream typed events for a run until the server closes the response.
    /// Pass the last seen sequence to resume after a reconnect instead of
    /// replaying from the start.
    public func streamAgentRun(
        runID: String,
        lastEventID: Int? = nil
    ) -> AsyncThrowingStream<AgentEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try await consumeAgentStream(
                        runID: runID,
                        lastEventID: lastEventID
                    ) { event in
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func consumeAgentStream(
        runID: String,
        lastEventID: Int?,
        yield: (AgentEvent) -> Void
    ) async throws {
        let url = try makeURL(path: "/agent/runs/\(runID)/events", query: [])
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if let lastEventID {
            request.setValue(String(lastEventID), forHTTPHeaderField: "Last-Event-ID")
        }
        if let token = currentToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        if http.statusCode == 401 {
            setToken(nil)
            await notifyUnauthorized()
            throw APIError.unauthorized
        }
        guard (200..<300).contains(http.statusCode) else {
            var data = Data()
            for try await byte in bytes {
                data.append(byte)
            }
            throw APIError.http(
                status: http.statusCode,
                message: APIClient.serverMessage(from: data) ?? "Request failed"
            )
        }

        var dataLines: [String] = []
        for try await rawLine in bytes.lines {
            let line = rawLine.hasSuffix("\r")
                ? String(rawLine.dropLast())
                : rawLine
            if line.isEmpty {
                if let event = Self.agentEvent(from: dataLines.joined(separator: "\n")) {
                    yield(event)
                }
                dataLines.removeAll()
            } else if line.hasPrefix("data:") {
                dataLines.append(
                    String(line.dropFirst(5))
                        .trimmingCharacters(in: .whitespaces)
                )
            }
        }
        if let event = Self.agentEvent(from: dataLines.joined(separator: "\n")) {
            yield(event)
        }
    }

    private static func agentEvent(from payload: String) -> AgentEvent? {
        guard
            !payload.isEmpty,
            let data = payload.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = object["type"] as? String
        else {
            return nil
        }
        return AgentEvent(
            type: type,
            delta: object["delta"] as? String,
            agent: object["agent"] as? String,
            step: object["step"] as? Int,
            toolCallID: object["tool_call_id"] as? String,
            name: object["name"] as? String,
            arguments: (object["arguments"]).map(jsonText),
            result: (object["result"]).map(jsonText),
            isError: object["is_error"] as? Bool ?? false,
            message: object["message"] as? String
        )
    }

    private static func jsonText(_ value: Any) -> String {
        if let string = value as? String {
            return string
        }
        if JSONSerialization.isValidJSONObject(value),
           let data = try? JSONSerialization.data(
               withJSONObject: value,
               options: [.prettyPrinted, .sortedKeys]
           ),
           let text = String(data: data, encoding: .utf8) {
            return text
        }
        return String(describing: value)
    }

    // MARK: - Transport

    private func request<T: Decodable>(
        _ method: String,
        path: String,
        query: [URLQueryItem] = [],
        body: (any Encodable)? = nil,
        authenticated: Bool = true
    ) async throws -> T {
        let data = try await send(
            method,
            path: path,
            query: query,
            body: body,
            authenticated: authenticated
        )
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    @discardableResult
    private func send(
        _ method: String,
        path: String,
        query: [URLQueryItem] = [],
        body: (any Encodable)? = nil,
        authenticated: Bool = true
    ) async throws -> Data {
        let url = try makeURL(path: path, query: query)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do {
                request.httpBody = try encoder.encode(body)
            } catch {
                throw APIError.decoding(error)
            }
        }

        if authenticated, let token = currentToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }

            if http.statusCode == 401, authenticated {
                setToken(nil)
                await notifyUnauthorized()
                throw APIError.unauthorized
            }

            guard (200..<300).contains(http.statusCode) else {
                throw APIError.http(
                    status: http.statusCode,
                    message: APIClient.serverMessage(from: data) ?? "Request failed"
                )
            }
            return data
        } catch let error as APIError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.transport(error)
        }
    }

    private func makeURL(path: String, query: [URLQueryItem]) throws -> URL {
        guard var components = URLComponents(
            url: baseURL,
            resolvingAgainstBaseURL: false
        ) else {
            throw APIError.invalidURL
        }
        let basePath = components.path.hasSuffix("/")
            ? String(components.path.dropLast())
            : components.path
        components.path = basePath + path
        components.queryItems = query.isEmpty ? nil : query
        guard let url = components.url else {
            throw APIError.invalidURL
        }
        return url
    }

    private func currentToken() -> String? {
        lock.lock()
        defer { lock.unlock() }
        return token
    }

    private func currentUnauthorizedHandler() -> (@Sendable () async -> Void)? {
        lock.lock()
        defer { lock.unlock() }
        return unauthorizedHandler
    }

    private func notifyUnauthorized() async {
        let handler = currentUnauthorizedHandler()
        await handler?()
    }

    private static func serverMessage(from data: Data) -> String? {
        guard
            let object = try? JSONSerialization.jsonObject(with: data),
            let dictionary = object as? [String: Any]
        else {
            return nil
        }
        if let detail = dictionary["detail"] as? String {
            return detail
        }
        if let detail = dictionary["detail"] as? [String: Any],
           let message = detail["message"] as? String {
            return message
        }
        return dictionary["message"] as? String
    }
}
