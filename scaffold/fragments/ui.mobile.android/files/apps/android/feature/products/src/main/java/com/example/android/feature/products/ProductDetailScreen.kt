package com.example.android.feature.products

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.example.android.core.model.Product
import com.example.android.core.network.ApiClient
import com.example.android.core.network.userMessage
import com.example.android.core.ui.formatApiDate
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Product detail with edit and confirmed delete actions. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductDetailScreen(
    api: ApiClient,
    productId: Long,
    onBack: () -> Unit,
    onEdit: () -> Unit,
    onDeleted: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var product by remember { mutableStateOf<Product?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var confirmingDelete by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(reloadToken) {
        loading = true
        error = null
        try {
            product = api.product(productId)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.userMessage()
        } finally {
            loading = false
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text(product?.name ?: "Product", modifier = Modifier.semantics { heading() }) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (product != null) {
                        IconButton(onClick = onEdit) {
                            Icon(Icons.Filled.Edit, contentDescription = "Edit product")
                        }
                        IconButton(onClick = { confirmingDelete = true }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Delete product")
                        }
                    }
                },
            )
        },
    ) { innerPadding ->
        val current = product
        val currentError = error
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when {
                loading -> LoadingState()
                currentError != null -> ErrorState(
                    message = currentError,
                    onRetry = { reloadToken += 1 },
                )
                current == null -> EmptyState(
                    title = "Product not found",
                    detail = "It may have been deleted.",
                )
                else -> ProductDetails(current)
            }
        }
    }

    if (confirmingDelete) {
        AlertDialog(
            onDismissRequest = { if (!deleting) confirmingDelete = false },
            title = { Text("Delete product?") },
            text = {
                Text("This removes the product from the API and cannot be undone.")
            },
            confirmButton = {
                TextButton(
                    enabled = !deleting,
                    onClick = {
                        deleting = true
                        scope.launch {
                            try {
                                api.deleteProduct(productId)
                                onDeleted()
                            } catch (e: CancellationException) {
                                throw e
                            } catch (e: Exception) {
                                error = e.userMessage()
                                confirmingDelete = false
                            } finally {
                                deleting = false
                            }
                        }
                    },
                ) {
                    Text(if (deleting) "Deleting..." else "Delete")
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !deleting,
                    onClick = { confirmingDelete = false },
                ) {
                    Text("Cancel")
                }
            },
        )
    }
}

@Composable
private fun ProductDetails(product: Product) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            product.name,
            modifier = Modifier.semantics { heading() },
            style = MaterialTheme.typography.headlineMedium,
        )
        Text(
            text = formatPrice(product.priceCents),
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
        HorizontalDivider()
        DetailValue("Description", product.description.ifBlank { "No description." })
        DetailValue("Created", formatApiDate(product.createdAt))
        DetailValue("Updated", formatApiDate(product.updatedAt))
        DetailValue("Product ID", product.id.toString())
    }
}

@Composable
private fun DetailValue(label: String, value: String) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(text = value, style = MaterialTheme.typography.bodyLarge)
    }
}
