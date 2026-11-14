package com.example.android.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelsTest {
    @Test
    fun decodesLoginResponseWithSnakeCaseFields() {
        val payload = """
            {
              "token": "session-token",
              "must_change_password": false,
              "user": {
                "id": 7,
                "username": "alice",
                "email": "alice@example.com",
                "phone": null,
                "display_name": "Alice",
                "is_active": true,
                "must_change_password": false,
                "created_at": "2026-01-01T00:00:00Z",
                "role_codes": ["admin", "user"],
                "permissions": ["products.read"]
              }
            }
        """.trimIndent()

        val response = apiJson.decodeFromString(LoginResponse.serializer(), payload)

        assertEquals("session-token", response.token)
        assertEquals("alice", response.user.username)
        assertEquals("Alice", response.user.displayName)
        assertEquals(listOf("admin", "user"), response.user.roleCodes)
        assertTrue(response.user.isActive)
    }

    @Test
    fun decodesProductListWithPriceCents() {
        val payload = """
            [
              {
                "id": 1,
                "name": "Desk lamp",
                "description": "Warm light",
                "price_cents": 4250,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z"
              }
            ]
        """.trimIndent()

        val products = apiJson.decodeFromString(
            kotlinx.serialization.builtins.ListSerializer(Product.serializer()),
            payload,
        )

        assertEquals(1, products.size)
        assertEquals(4250, products.single().priceCents)
        assertEquals("Desk lamp", products.single().name)
    }

    @Test
    fun encodesAgentFeedbackRequest() {
        val encoded = apiJson.encodeToString(
            AgentFeedbackRequest.serializer(),
            AgentFeedbackRequest(agent = "products", rating = 5, comment = "useful"),
        )

        assertTrue(encoded.contains("\"agent\":\"products\""))
        assertTrue(encoded.contains("\"rating\":5"))
        assertTrue(encoded.contains("\"comment\":\"useful\""))
    }

    @Test
    fun omitsNullProfileFieldsWhenEncoding() {
        val encoded = apiJson.encodeToString(
            ProfileUpdate.serializer(),
            ProfileUpdate(displayName = "Alice"),
        )

        assertTrue(encoded.contains("display_name"))
        assertFalse(encoded.contains("\"email\""))
        assertFalse(encoded.contains("\"phone\""))
    }
}
