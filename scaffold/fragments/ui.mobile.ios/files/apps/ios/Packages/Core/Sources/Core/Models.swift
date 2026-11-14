import Contracts
import Foundation

// Public wire DTOs are generated from contracts/openapi.yaml by the Contracts
// package. The UI consumes these types directly; no hand-written duplicate
// models are maintained in Core.

public typealias User = Contracts.UserRead
public typealias AuthSession = Contracts.LoginResponse
public typealias MeResponse = Contracts.MeResponse
public typealias Product = Contracts.Product
