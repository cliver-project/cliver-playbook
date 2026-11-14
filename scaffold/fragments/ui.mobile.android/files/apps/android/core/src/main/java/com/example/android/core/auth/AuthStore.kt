package com.example.android.core.auth

import com.example.android.core.model.LoginRequest
import com.example.android.core.model.LoginResponse
import com.example.android.core.model.ProfileUpdate
import com.example.android.core.model.RegisterRequest
import com.example.android.core.model.User
import com.example.android.core.network.ApiClient
import com.example.android.core.network.ApiException
import com.example.android.core.network.userMessage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext

data class AuthState(
    val token: String? = null,
    val user: User? = null,
    val restoring: Boolean = false,
    val busy: Boolean = false,
    val error: String? = null,
)

/**
 * Session owner for the app: sign-in, registration, profile updates and the
 * 401-to-sign-in transition. Compose observes [state]; the client reads the
 * token through [token].
 */
class AuthStore(
    private val api: ApiClient,
    private val tokens: TokenStore,
) {
    private val storedToken = tokens.read()

    private val _state = MutableStateFlow(
        AuthState(token = storedToken, restoring = storedToken != null),
    )
    val state: StateFlow<AuthState> = _state.asStateFlow()

    /** The token used by the API client; null when signed out. */
    fun token(): String? = _state.value.token

    suspend fun login(username: String, password: String) {
        authenticate { api.login(LoginRequest(username = username, password = password)) }
    }

    suspend fun register(
        username: String,
        password: String,
        email: String,
        displayName: String,
    ) {
        authenticate {
            api.register(
                RegisterRequest(
                    username = username,
                    password = password,
                    email = email.takeIf { it.isNotBlank() },
                    displayName = displayName.takeIf { it.isNotBlank() },
                ),
            )
        }
    }

    /** Loads /auth/me when a stored token exists. Called once at app start. */
    suspend fun restoreSession() {
        if (_state.value.token == null) {
            _state.update { it.copy(restoring = false) }
            return
        }
        loadProfile()
    }

    /** Reloads the signed-in user, for example after a failed startup call. */
    suspend fun refreshProfile() {
        if (_state.value.token == null) return
        loadProfile()
    }

    /** Saves the editable profile fields; returns true when the server accepted it. */
    suspend fun updateProfile(displayName: String, email: String, phone: String): Boolean {
        _state.update { it.copy(busy = true, error = null) }
        return try {
            val response = api.updateProfile(
                ProfileUpdate(email = email, phone = phone, displayName = displayName),
            )
            _state.update { it.copy(user = response.user, busy = false) }
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { it.copy(busy = false, error = e.userMessage()) }
            false
        }
    }

    fun logout() {
        tokens.clear()
        _state.value = AuthState()
    }

    /** Clears the rejected token and returns the app to sign-in. */
    fun handleUnauthorized() {
        tokens.clear()
        _state.value = AuthState(error = "Your session expired. Sign in again.")
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }

    private suspend fun authenticate(call: suspend () -> LoginResponse) {
        _state.update { it.copy(busy = true, error = null) }
        try {
            val response = call()
            withContext(Dispatchers.IO) { tokens.write(response.token) }
            _state.value = AuthState(token = response.token, user = response.user)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { it.copy(busy = false, restoring = false, error = e.userMessage()) }
        }
    }

    private suspend fun loadProfile() {
        _state.update { it.copy(restoring = true, error = null) }
        try {
            val response = api.me()
            _state.update { it.copy(user = response.user, restoring = false) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (e is ApiException && e.status == 401) {
                handleUnauthorized()
            } else {
                _state.update { it.copy(restoring = false, error = e.userMessage()) }
            }
        }
    }
}
