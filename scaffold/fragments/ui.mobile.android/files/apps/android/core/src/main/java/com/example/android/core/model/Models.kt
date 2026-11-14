package com.example.android.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * Wire DTOs are generated from contracts/openapi.yaml in the `:contracts`
 * module. These aliases keep feature imports stable while removing the
 * hand-written duplicates.
 */
typealias User = com.example.android.contracts.models.UserRead
typealias AuthSession = com.example.android.contracts.models.LoginResponse
typealias LoginRequest = com.example.android.contracts.models.LoginRequest
typealias LoginResponse = com.example.android.contracts.models.LoginResponse
typealias MeResponse = com.example.android.contracts.models.MeResponse
typealias RegisterRequest = com.example.android.contracts.models.RegisterRequest
typealias ProfileUpdate = com.example.android.contracts.models.ProfileUpdate
typealias Product = com.example.android.contracts.models.Product
typealias ProductInput = com.example.android.contracts.models.ProductCreate
typealias AgentFeedbackRequest = com.example.android.contracts.models.AgentFeedbackRequest

/**
 * JSON configuration shared by the SSE parser.
 *
 * Unknown keys are ignored so a server can add fields without breaking an
 * installed client. Tool arguments/results stay as raw JSON so the reference
 * tool card does not couple Core to one event schema.
 */
val apiJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}

@Serializable
data class AgentEvent(
    val type: String,
    val delta: String? = null,
    val agent: String? = null,
    val step: Int? = null,
    @SerialName("tool_call_id") val toolCallId: String? = null,
    val name: String? = null,
    val arguments: JsonElement? = null,
    val result: JsonElement? = null,
    @SerialName("is_error") val isError: Boolean = false,
    val message: String? = null,
)
