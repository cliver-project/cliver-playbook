package com.example.android.core.network

import com.example.android.contracts.apis.AgentApi
import com.example.android.contracts.apis.AuthApi
import com.example.android.contracts.apis.ProductsApi
import com.example.android.contracts.infrastructure.ApiResponse
import com.example.android.contracts.infrastructure.ClientError
import com.example.android.contracts.infrastructure.ResponseType
import com.example.android.contracts.infrastructure.ServerError
import com.example.android.contracts.infrastructure.Success
import com.example.android.contracts.models.AgentFeedbackRequest
import com.example.android.contracts.models.AgentRunRequest
import com.example.android.contracts.models.LoginRequest
import com.example.android.contracts.models.LoginResponse
import com.example.android.contracts.models.MeResponse
import com.example.android.contracts.models.Product
import com.example.android.contracts.models.ProductCreate
import com.example.android.contracts.models.ProductUpdate
import com.example.android.contracts.models.ProfileUpdate
import com.example.android.contracts.models.RegisterRequest
import com.example.android.core.model.AgentEvent
import com.example.android.core.model.ProductInput
import com.example.android.core.model.apiJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

/** An HTTP error returned by the API. Message is already user-presentable. */
class ApiException(val status: Int, override val message: String) : IOException(message)

/**
 * Bearer-token HTTP client backed by the generated `:contracts` API classes.
 *
 * The token is read through [tokenProvider] on every request, so signing in or
 * out does not need a new client. A 401 invokes [onUnauthorized] once per
 * request; the session owner clears secure storage and returns to sign-in.
 * Run events stay a custom SSE transport because OpenAPI does not model SSE.
 */
class ApiClient(
    baseUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val base: HttpUrl = baseUrl.trimEnd('/').toHttpUrl()

    // Generated request paths already include the /api/v1 prefix; the API
    // classes need the origin only. SSE builds on [base] because it appends
    // the documented relative path itself.
    private val origin = base.newBuilder()
        .encodedPath("/")
        .query(null)
        .fragment(null)
        .build()
        .toString()
        .trimEnd('/')

    var tokenProvider: () -> String? = { null }
    var onUnauthorized: (() -> Unit)? = null

    private val authApi = AuthApi(origin, client).apply {
        accessTokenProvider = { tokenProvider() }
    }
    private val productsApi = ProductsApi(origin, client).apply {
        accessTokenProvider = { tokenProvider() }
    }
    private val agentApi = AgentApi(origin, client).apply {
        accessTokenProvider = { tokenProvider() }
    }

    suspend fun login(body: LoginRequest): LoginResponse =
        execute { authApi.loginWithHttpInfo(body) }

    suspend fun register(body: RegisterRequest): LoginResponse =
        execute { authApi.registerWithHttpInfo(body) }

    suspend fun me(): MeResponse =
        execute { authApi.meWithHttpInfo() }

    suspend fun updateProfile(body: ProfileUpdate): MeResponse =
        execute { authApi.updateProfileWithHttpInfo(body) }

    suspend fun products(limit: Int = 50, offset: Int = 0): List<Product> =
        execute { productsApi.listProductsWithHttpInfo(limit.toLong(), offset.toLong()) }

    suspend fun product(id: Long): Product =
        execute { productsApi.getProductWithHttpInfo(id) }

    suspend fun createProduct(body: ProductInput): Product =
        execute { productsApi.createProductWithHttpInfo(body) }

    suspend fun updateProduct(id: Long, body: ProductInput): Product =
        execute {
            productsApi.updateProductWithHttpInfo(
                id,
                ProductUpdate(
                    name = body.name,
                    description = body.description,
                    priceCents = body.priceCents,
                ),
            )
        }

    suspend fun deleteProduct(id: Long) =
        executeNoContent { productsApi.deleteProductWithHttpInfo(id) }

    // MARK: - Agent runs

    /** Start a coordinator run and return its id. */
    suspend fun startAgentRun(message: String, idempotencyKey: String? = null): String =
        execute {
            agentApi.createAgentRunWithHttpInfo(
                AgentRunRequest(message = message),
                idempotencyKey,
            )
        }.runId

    /** Ask the API to cancel a run. Best-effort from the chat surface. */
    suspend fun cancelAgentRun(runID: String) =
        executeNoContent { agentApi.cancelAgentRunWithHttpInfo(runID) }

    /** Attach the user's outcome rating to one completed run. */
    suspend fun submitAgentFeedback(
        runID: String,
        agentName: String,
        rating: Int,
        comment: String = "",
    ) {
        execute {
            agentApi.submitAgentFeedbackWithHttpInfo(
                runID,
                AgentFeedbackRequest(
                    agent = agentName,
                    rating = rating.toLong(),
                    comment = comment,
                ),
            )
        }
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
        val request = Request.Builder()
            .url(url("/agent/runs/$runId/events"))
            .header("Accept", "text/event-stream")
            .apply {
                if (lastEventId != null) {
                    header("Last-Event-ID", lastEventId.toString())
                }
                tokenProvider()?.takeIf { it.isNotBlank() }?.let {
                    header("Authorization", "Bearer $it")
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

    private suspend fun <T : Any> execute(block: suspend () -> ApiResponse<T?>): T {
        val response = block()
        return when (response.responseType) {
            ResponseType.Success -> (response as Success<T?>).data
                ?: throw ApiException(response.statusCode, "The API returned an empty response.")
            ResponseType.ClientError -> throw clientError(response as ClientError<*>)
            ResponseType.ServerError -> throw serverError(response as ServerError<*>)
            else -> throw ApiException(
                response.statusCode,
                "The API returned an unexpected response (${response.statusCode}).",
            )
        }
    }

    private suspend fun executeNoContent(block: suspend () -> ApiResponse<Unit?>) {
        val response = block()
        when (response.responseType) {
            ResponseType.Success -> return
            ResponseType.ClientError -> throw clientError(response as ClientError<*>)
            ResponseType.ServerError -> throw serverError(response as ServerError<*>)
            else -> throw ApiException(
                response.statusCode,
                "The API returned an unexpected response (${response.statusCode}).",
            )
        }
    }

    private fun clientError(error: ClientError<*>): ApiException {
        if (error.statusCode == 401) onUnauthorized?.invoke()
        return ApiException(error.statusCode, errorMessage(error.statusCode, error.body as? String))
    }

    private fun serverError(error: ServerError<*>): ApiException {
        val body = error.body as? String
        if (body.isNullOrBlank()) {
            return ApiException(error.statusCode, error.message ?: "The API failed to handle the request.")
        }
        return ApiException(error.statusCode, errorMessage(error.statusCode, body))
    }

    private fun url(path: String): HttpUrl =
        base.newBuilder().addPathSegments(path.trim('/')).build()
}

/** A user-facing sentence for any failure raised by the client. */
fun Throwable.userMessage(): String = when (this) {
    is ApiException -> message
    is IOException -> "Cannot reach the API. Check the connection and the base URL."
    is SerializationException -> "The API returned an unexpected response."
    else -> message ?: "Something went wrong."
}

private fun errorMessage(status: Int, payload: String?): String {
    if (payload.isNullOrBlank()) {
        return "Request failed with status $status."
    }
    val detail = try {
        (apiJson.parseToJsonElement(payload) as? JsonObject)?.get("detail")
    } catch (e: SerializationException) {
        null
    }
    return (detail as? JsonPrimitive)?.contentOrNull ?: "Request failed with status $status."
}
