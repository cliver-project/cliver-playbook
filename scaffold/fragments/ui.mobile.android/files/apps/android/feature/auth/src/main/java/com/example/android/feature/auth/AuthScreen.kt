package com.example.android.feature.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.android.core.auth.AuthStore
import kotlinx.coroutines.launch

/**
 * Sign-in and registration against the project API. Registering signs the user
 * in immediately because the endpoint returns the same session response.
 */
@Composable
fun AuthScreen(
    store: AuthStore,
    title: String,
    modifier: Modifier = Modifier,
) {
    val state by store.state.collectAsState()
    var registerMode by rememberSaveable { mutableStateOf(false) }
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var displayName by rememberSaveable { mutableStateOf("") }
    var passwordVisible by rememberSaveable { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val message = localError ?: state.error

    fun submit() {
        localError = when {
            username.isBlank() -> "Enter a username."
            !registerMode && password.isEmpty() -> "Enter your password."
            registerMode && password.length < 8 ->
                "Use at least 8 characters for the password."
            registerMode && email.isNotBlank() && !email.contains('@') ->
                "Enter a valid email address or leave it empty."
            else -> null
        }
        if (localError != null) return
        scope.launch {
            if (registerMode) {
                store.register(
                    username = username.trim(),
                    password = password,
                    email = email.trim(),
                    displayName = displayName.trim(),
                )
            } else {
                store.login(username.trim(), password)
            }
        }
    }

    Surface(modifier = modifier.fillMaxSize()) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .systemBarsPadding()
                .padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .widthIn(max = 420.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = title,
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.headlineMedium,
                    textAlign = TextAlign.Center,
                )
                Text(
                    text = if (registerMode) {
                        "Create an account with the project API."
                    } else {
                        "Sign in to continue."
                    },
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.bodyMedium,
                    textAlign = TextAlign.Center,
                )

                if (message != null) {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer,
                        ),
                    ) {
                        Text(
                            text = message,
                            modifier = Modifier.padding(12.dp),
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }

                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Username") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Text,
                        imeAction = ImeAction.Next,
                    ),
                )

                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = if (passwordVisible) {
                        VisualTransformation.None
                    } else {
                        PasswordVisualTransformation()
                    },
                    trailingIcon = {
                        TextButton(onClick = { passwordVisible = !passwordVisible }) {
                            Text(if (passwordVisible) "Hide" else "Show")
                        }
                    },
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Password,
                        imeAction = if (registerMode) ImeAction.Next else ImeAction.Done,
                    ),
                    keyboardActions = KeyboardActions(onDone = { submit() }),
                )

                if (registerMode) {
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Email (optional)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Email,
                            imeAction = ImeAction.Next,
                        ),
                    )
                    OutlinedTextField(
                        value = displayName,
                        onValueChange = { displayName = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Display name (optional)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Text,
                            imeAction = ImeAction.Done,
                        ),
                        keyboardActions = KeyboardActions(onDone = { submit() }),
                    )
                }

                Button(
                    onClick = { submit() },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.busy,
                ) {
                    if (state.busy) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    } else {
                        Text(if (registerMode) "Create account" else "Sign in")
                    }
                }

                TextButton(
                    onClick = {
                        registerMode = !registerMode
                        localError = null
                        store.clearError()
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.busy,
                ) {
                    Text(
                        if (registerMode) {
                            "Already have an account? Sign in"
                        } else {
                            "Need an account? Register"
                        },
                    )
                }
            }
        }
    }
}
