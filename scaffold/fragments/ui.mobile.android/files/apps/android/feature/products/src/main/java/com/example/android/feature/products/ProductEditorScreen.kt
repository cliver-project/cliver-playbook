package com.example.android.feature.products

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.example.android.core.model.ProductInput
import com.example.android.core.network.ApiClient
import com.example.android.core.network.userMessage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Create and edit form for the reference product slice. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductEditorScreen(
    api: ApiClient,
    productId: Int?,
    onBack: () -> Unit,
    onSaved: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isEditing = productId != null
    var loading by remember { mutableStateOf(isEditing) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var loaded by remember { mutableStateOf(!isEditing) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var name by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var price by rememberSaveable { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(productId, reloadToken) {
        if (productId == null) return@LaunchedEffect
        loading = true
        error = null
        try {
            val product = api.product(productId)
            name = product.name
            description = product.description
            price = formatPrice(product.priceCents)
            loaded = true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.userMessage()
        } finally {
            loading = false
        }
    }

    fun save() {
        val cents = parsePriceToCents(price)
        error = when {
            name.isBlank() -> "Enter a product name."
            cents == null -> "Enter a price as a number, for example 12.50."
            else -> null
        }
        if (cents == null || error != null) return
        val input = ProductInput(
            name = name.trim(),
            description = description.trim(),
            priceCents = cents,
        )
        saving = true
        scope.launch {
            try {
                if (productId == null) {
                    api.createProduct(input)
                } else {
                    api.updateProduct(productId, input)
                }
                onSaved()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = e.userMessage()
            } finally {
                saving = false
            }
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text(if (isEditing) "Edit product" else "New product") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { innerPadding ->
        val currentError = error
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when {
                loading -> LoadingState()
                currentError != null && !loaded -> ErrorState(
                    message = currentError,
                    onRetry = { reloadToken += 1 },
                )
                else -> Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (currentError != null) {
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.errorContainer,
                            ),
                        ) {
                            Text(
                                text = currentError,
                                modifier = Modifier.padding(12.dp),
                                color = MaterialTheme.colorScheme.onErrorContainer,
                            )
                        }
                    }

                    OutlinedTextField(
                        value = name,
                        onValueChange = { name = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Name") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    )
                    OutlinedTextField(
                        value = description,
                        onValueChange = { description = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Description") },
                        minLines = 3,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
                    )
                    OutlinedTextField(
                        value = price,
                        onValueChange = { price = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Price") },
                        supportingText = { Text("Amount in the API's currency, for example 12.50.") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Decimal,
                            imeAction = ImeAction.Done,
                        ),
                    )

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Button(
                            onClick = { save() },
                            modifier = Modifier.weight(1f),
                            enabled = !saving,
                        ) {
                            if (saving) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(20.dp),
                                    strokeWidth = 2.dp,
                                    color = MaterialTheme.colorScheme.onPrimary,
                                )
                            } else {
                                Text(if (isEditing) "Save changes" else "Create product")
                            }
                        }
                        OutlinedButton(
                            onClick = onBack,
                            modifier = Modifier.weight(1f),
                            enabled = !saving,
                        ) {
                            Text("Cancel")
                        }
                    }
                }
            }
        }
    }
}
