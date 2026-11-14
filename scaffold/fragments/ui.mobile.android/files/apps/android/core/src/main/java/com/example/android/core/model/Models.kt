package com.example.android.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * JSON configuration shared by the API client and its tests.
 *
 * Unknown keys are ignored so a server can add fields without breaking an
 * installed client. Null values are omitted when encoding, which matches the
 * API's PATCH convention: an absent field is unchanged.
 */
val apiJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}

@Serializable
data class User(
    val id: Int,
    val username: String,
    val email: String? = null,
    val phone: String? = null,
    @SerialName("display_name") val displayName: String,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
    @SerialName("created_at") val createdAt: String,
    @SerialName("role_codes") val roleCodes: List<String> = emptyList(),
    val permissions: List<String> = emptyList(),
)

@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
)

@Serializable
data class RegisterRequest(
    val username: String,
    val password: String,
    val email: String? = null,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
data class LoginResponse(
    val token: String,
    @SerialName("must_change_password") val mustChangePassword: Boolean,
    val user: User,
)

@Serializable
data class MeResponse(
    val user: User,
)

@Serializable
data class AgentFeedbackRequest(
    val agent: String,
    val rating: Int,
    val comment: String = "",
)

@Serializable
data class ProfileUpdate(
    val email: String? = null,
    val phone: String? = null,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
data class Product(
    val id: Int,
    val name: String,
    val description: String = "",
    @SerialName("price_cents") val priceCents: Int,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class ProductInput(
    val name: String,
    val description: String,
    @SerialName("price_cents") val priceCents: Int,
)

/**
 * One typed event from `GET /api/v1/agent/runs/{id}/events`.
 *
 * The API event union is wide; the chat surface only needs the common fields.
 * Tool arguments and results stay as JSON so the reference tool card can show
 * them without coupling Core to one event schema.
 */
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
