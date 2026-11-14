package com.example.android.core.network

import com.example.android.core.model.AgentEvent
import com.example.android.core.model.AgentFeedbackRequest
import com.example.android.core.model.LoginRequest
import com.example.android.core.model.LoginResponse
import com.example.android.core.model.MeResponse
import com.example.android.core.model.Product
import com.example.android.core.model.ProductInput
import com.example.android.core.model.ProfileUpdate
import com.example.android.core.model.RegisterRequest
import com.example.android.core.model.apiJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.SerializationStrategy
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

private val JSON = "application/json".toMediaType()

@Serializable
private data class AgentRunRequest(val message: String)

@Serializable
private data class AgentRunCreated(
    @SerialName("run_id") val runId: String,
)

/** An HTTP error returned by the API. Message is already user-presentable. */
class ApiException(val status: Int, override val message: String) : IOException(message)

/**
 * Small bearer-token HTTP client for the generated API contract.
 *
 * The token is read through [tokenProvider] on every request, so signing in or
 * out does not need a new client. A 401 invokes [onUnauthorized] once per
 * request; the session owner clears secure storage and returns to sign-in.
 */
class ApiClient(
    baseUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val base = baseUrl.trimEnd('/').toHttpUrl()

    var tokenProvider: () -> String? = { null }
    var onUnauthorized: (() -> Unit)? = null

    suspend fun login(body: LoginRequest): LoginResponse =
        execute(
            requestBuilder("/auth/login").post(jsonBody(body, LoginRequest.serializer())).build(),
            LoginResponse.serializer(),
        )

    suspend fun register(body: RegisterRequest): LoginResponse =
        execute(
            requestBuilder("/auth/register").post(jsonBody(body, RegisterRequest.serializer())).build(),
            LoginResponse.serializer(),
        )

    suspend fun me(): MeResponse =
        execute(requestBuilder("/auth/me").get().build(), MeResponse.serializer())

    suspend fun updateProfile(body: ProfileUpdate): MeResponse =
        execute(
            requestBuilder("/auth/profile")
                .patch(jsonBody(body, ProfileUpdate.serializer()))
                .build(),
            MeResponse.serializer(),
        )

    suspend fun products(limit: Int = 50, offset: Int = 0): List<Product> =
        execute(
            requestBuilder(
                "/products",
                mapOf("limit" to limit.toString(), "offset" to offset.toString()),
            ).get().build(),
            ListSerializer(Product.serializer()),
        )

    suspend fun product(id: Int): Product =
        execute(requestBuilder("/products/$id").get().build(), Product.serializer())

    suspend fun createProduct(body: ProductInput): Product =
        execute(
            requestBuilder("/products").post(jsonBody(body, ProductInput.serializer())).build(),
            Product.serializer(),
        )

    suspend fun updateProduct(id: Int, body: ProductInput): Product =
        execute(
            requestBuilder("/products/$id")
                .patch(jsonBody(body, ProductInput.serializer()))
                .build(),
            Product.serializer(),
        )

    suspend fun deleteProduct(id: Int) {
        executeNoContent(requestBuilder("/products/$id").delete().build())
    }

    // MARK: - Agent runs

    /** Start a coordinator run and return its id. */
    suspend fun startAgentRun(message: String): String =
        execute(
            requestBuilder("/agent/runs")
                .post(jsonBody(AgentRunRequest(message), AgentRunRequest.serializer()))
                .build(),
            AgentRunCreated.serializer(),
        ).runId

    /** Ask the API to cancel a run. Best-effort from the chat surface. */
    suspend fun cancelAgentRun(runID: String) {
        executeNoContent(
            requestBuilder("/agent/runs/$runID/cancel")
                .post("{}".toRequestBody(JSON))
                .build(),
        )
    }

    /** Attach the user's outcome rating to one completed run. */
    suspend fun submitAgentFeedback(
        runID: String,
        agent: String,
        rating: Int,
        comment: String = "",
    ) {
        executeNoContent(
            requestBuilder("/agent/runs/$runID/feedback")
                .post(
                    jsonBody(
                        AgentFeedbackRequest(agent = agent, rating = rating, comment = comment),
                        AgentFeedbackRequest.serializer(),
                    ),
                )
                .build(),
        )
    }

    /**
     * Stream typed run events until the server closes the response. Pass the
     * last seen sequence to resume after a reconnect instead of replaying
     * from the start.
     *
     * `callbackFlow` owns the OkHttp call: leaving the chat screen cancels the
     * call instead of leaking a background read. The collector runs on the
     * caller's dispatcher; this method reads on IO.
     */
    fun streamAgentRun(runId: String, lastEventId: Long? = null): Flow<AgentEvent> = callbackFlow {
        val request = requestBuilder("/agent/runs/$runId/events")
            .header("Accept", "text/event-stream")
            .apply {
                if (lastEventId != null) {
                    header("Last-Event-ID", lastEventId.toString())
                }
            }
            .get()
            .build()
        val call = client.newCall(request)

        fun emit(payload: String) {
            if (payload.isBlank()) return
            try {
                trySend(apiJson.decodeFromString(AgentEvent.serializer(), payload))
            } catch (_: SerializationException) {
                // A keepalive or malformed block must not kill the stream.
            }
        }

        val job = launch(Dispatchers.IO) {
            try {
                call.execute().use { response ->
                    if (response.code == 401) onUnauthorized?.invoke()
                    if (!response.isSuccessful) {
                        throw ApiException(
                            response.code,
                            errorMessage(response.code, response.body?.string().orEmpty()),
                        )
                    }
                    val source = response.body?.source()
                        ?: throw ApiException(response.code, "The API returned an empty stream.")
                    val data = StringBuilder()
                    while (true) {
                        val line = source.readUtf8Line()?.trimEnd('\r') ?: break
                        if (line.isEmpty()) {
                            emit(data.toString())
                            data.clear()
                        } else if (line.startsWith("data:")) {
                            if (data.isNotEmpty()) data.append('\n')
                            data.append(line.removePrefix("data:").trim())
                        }
                    }
                    emit(data.toString())
                }
                close()
            } catch (e: CancellationException) {
                close(e)
            } catch (e: Exception) {
                close(e)
            }
        }

        awaitClose {
            call.cancel()
            job.cancel()
        }
    }

    private fun requestBuilder(path: String, query: Map<String, String> = emptyMap()): Request.Builder {
        val builder = Request.Builder().url(url(path, query))
        val token = tokenProvider()
        if (!token.isNullOrBlank()) {
            builder.header("Authorization", "Bearer $token")
        }
        return builder
    }

    private fun url(path: String, query: Map<String, String>): HttpUrl {
        val builder = base.newBuilder().addPathSegments(path.trim('/'))
        query.forEach { (key, value) -> builder.addQueryParameter(key, value) }
        return builder.build()
    }

    private fun <T> jsonBody(value: T, serializer: SerializationStrategy<T>): RequestBody =
        apiJson.encodeToString(serializer, value).toRequestBody(JSON)

    private suspend fun <T> execute(
        request: Request,
        deserializer: DeserializationStrategy<T>,
    ): T = withContext(Dispatchers.IO) {
        client.newCall(request).execute().use { response ->
            val payload = response.body?.string().orEmpty()
            if (response.code == 401) {
                onUnauthorized?.invoke()
            }
            if (!response.isSuccessful) {
                throw ApiException(response.code, errorMessage(response.code, payload))
            }
            try {
                apiJson.decodeFromString(deserializer, payload)
            } catch (e: SerializationException) {
                throw ApiException(response.code, "The API returned an unexpected response.")
            }
        }
    }

    private suspend fun executeNoContent(request: Request) = withContext(Dispatchers.IO) {
        client.newCall(request).execute().use { response ->
            if (response.code == 401) {
                onUnauthorized?.invoke()
            }
            if (!response.isSuccessful) {
                throw ApiException(
                    response.code,
                    errorMessage(response.code, response.body?.string().orEmpty()),
                )
            }
        }
    }
}

/** A user-facing sentence for any failure raised by the client. */
fun Throwable.userMessage(): String = when (this) {
    is ApiException -> message
    is IOException -> "Cannot reach the API. Check the connection and the base URL."
    is SerializationException -> "The API returned an unexpected response."
    else -> message ?: "Something went wrong."
}

private fun errorMessage(status: Int, payload: String): String {
    if (payload.isBlank()) {
        return "Request failed with status $status."
    }
    val detail = try {
        (apiJson.parseToJsonElement(payload) as? JsonObject)?.get("detail")
    } catch (e: SerializationException) {
        null
    }
    return (detail as? JsonPrimitive)?.contentOrNull ?: "Request failed with status $status."
}
