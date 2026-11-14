package com.example.android.core.network

import com.example.android.core.model.ProductInput
import com.example.android.core.model.RegisterRequest
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.UUID

/**
 * Opt-in check that the generated client and the running API agree. Set
 * `CLIVER_LIVE_API_URL` (for example `http://127.0.0.1:8000/api/v1`) and start
 * the API first. The test registers a fresh user, so it needs no seed data.
 */
class LiveApiClientTest {
    @Test
    fun registerMeAndProductsAgainstLiveApi() = runBlocking {
        val base = System.getenv("CLIVER_LIVE_API_URL")
        assumeTrue("Set CLIVER_LIVE_API_URL to run this test.", !base.isNullOrBlank())

        val client = ApiClient(base!!)
        val username = "live." + UUID.randomUUID().toString().replace("-", "").take(12)
        val session = client.register(
            RegisterRequest(
                username = username,
                password = "LiveContract!2345",
                email = null,
                displayName = "Live Contract",
            ),
        )

        assertFalse(session.token.isBlank())
        assertEquals(username, session.user.username)

        client.tokenProvider = { session.token }
        val me = client.me()
        assertEquals(username, me.user.username)
        assertEquals("Live Contract", me.user.displayName)
        val created = client.createProduct(
            ProductInput(name = "Live contract $username", description = "", priceCents = 123),
        )
        assertTrue(client.products().any { it.id == created.id })
        client.deleteProduct(created.id)
    }
}
