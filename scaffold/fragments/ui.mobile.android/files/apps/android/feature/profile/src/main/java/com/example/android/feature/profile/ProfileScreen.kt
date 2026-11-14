package com.example.android.feature.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.android.core.auth.AuthStore
import com.example.android.core.model.User
import com.example.android.core.ui.formatApiDate
import kotlinx.coroutines.launch

/**
 * Profile view and edit. The username is stable identity and is not editable;
 * email, phone and display name are the self-service fields.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    store: AuthStore,
    modifier: Modifier = Modifier,
) {
    val state by store.state.collectAsState()
    var editing by rememberSaveable { mutableStateOf(false) }
    var displayName by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var phone by rememberSaveable { mutableStateOf("") }
    var localError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val user = state.user

    LaunchedEffect(user?.id) {
        if (user == null && state.token != null && !state.busy) {
            store.refreshProfile()
        }
    }

    fun beginEdit(current: User) {
        displayName = current.displayName
        email = current.email.orEmpty()
        phone = current.phone.orEmpty()
        localError = null
        store.clearError()
        editing = true
    }

    fun save() {
        localError = when {
            displayName.isBlank() -> "Display name cannot be empty."
            email.isNotBlank() && !email.contains('@') ->
                "Enter a valid email address or leave it empty."
            else -> null
        }
        if (localError != null) return
        scope.launch {
            val saved = store.updateProfile(
                displayName = displayName.trim(),
                email = email.trim(),
                phone = phone.trim(),
            )
            if (saved) editing = false
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("Profile") },
                actions = {
                    if (user != null && !editing) {
                        IconButton(onClick = { beginEdit(user) }) {
                            Icon(Icons.Filled.Edit, contentDescription = "Edit profile")
                        }
                    }
                    IconButton(onClick = { store.logout() }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ExitToApp,
                            contentDescription = "Sign out",
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            val message = localError ?: state.error
            when {
                editing -> ProfileForm(
                    displayName = displayName,
                    onDisplayNameChange = { displayName = it },
                    email = email,
                    onEmailChange = { email = it },
                    phone = phone,
                    onPhoneChange = { phone = it },
                    busy = state.busy,
                    error = message,
                    onSave = { save() },
                    onCancel = {
                        editing = false
                        localError = null
                        store.clearError()
                    },
                )
                user == null && (state.restoring || state.busy) -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
                user == null -> ProfileUnavailable(
                    message = message ?: "The profile could not be loaded.",
                    onRetry = { scope.launch { store.refreshProfile() } },
                )
                else -> user?.let { ProfileDetails(it) }
            }
        }
    }
}

@Composable
private fun ProfileDetails(user: User) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = user.displayName.ifBlank { user.username },
            style = MaterialTheme.typography.headlineMedium,
        )
        Text(
            text = "@${user.username}",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        if (user.mustChangePassword) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                ),
            ) {
                Text(
                    text = "The API marks this account for a password change.",
                    modifier = Modifier.padding(16.dp),
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                DetailRow("Email", user.email ?: "Not set")
                DetailRow("Phone", user.phone ?: "Not set")
                DetailRow("Status", if (user.isActive) "Active" else "Inactive")
                val roles = user.roleCodes.orEmpty()
                DetailRow(
                    "Roles",
                    if (roles.isEmpty()) "None" else roles.joinToString(", "),
                )
                DetailRow("Member since", formatApiDate(user.createdAt))
            }
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(text = value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun ProfileForm(
    displayName: String,
    onDisplayNameChange: (String) -> Unit,
    email: String,
    onEmailChange: (String) -> Unit,
    phone: String,
    onPhoneChange: (String) -> Unit,
    busy: Boolean,
    error: String?,
    onSave: () -> Unit,
    onCancel: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Edit profile", style = MaterialTheme.typography.titleLarge)

        if (error != null) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ),
            ) {
                Text(
                    text = error,
                    modifier = Modifier.padding(12.dp),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }

        OutlinedTextField(
            value = displayName,
            onValueChange = onDisplayNameChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Display name") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
        )
        OutlinedTextField(
            value = email,
            onValueChange = onEmailChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Email") },
            supportingText = { Text("Leave empty to clear the address.") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Email,
                imeAction = ImeAction.Next,
            ),
        )
        OutlinedTextField(
            value = phone,
            onValueChange = onPhoneChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Phone") },
            supportingText = { Text("Leave empty to clear the number.") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Phone,
                imeAction = ImeAction.Done,
            ),
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Button(
                onClick = onSave,
                modifier = Modifier.weight(1f),
                enabled = !busy,
            ) {
                if (busy) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text("Save")
                }
            }
            OutlinedButton(
                onClick = onCancel,
                modifier = Modifier.weight(1f),
                enabled = !busy,
            ) {
                Text("Cancel")
            }
        }
    }
}

@Composable
private fun ProfileUnavailable(message: String, onRetry: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = "Profile unavailable",
            style = MaterialTheme.typography.titleMedium,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
        Spacer(modifier = Modifier.height(16.dp))
        Button(onClick = onRetry) { Text("Retry") }
    }
}
