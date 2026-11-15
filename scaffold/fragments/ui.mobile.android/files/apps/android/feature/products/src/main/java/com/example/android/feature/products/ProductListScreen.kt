package com.example.android.feature.products

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.example.android.core.model.Product
import com.example.android.core.network.ApiClient
import com.example.android.core.network.userMessage
import com.example.android.core.ui.LayoutMode
import com.example.android.core.ui.LocalAppComponents
import com.example.android.core.ui.currentLayoutMode
import kotlinx.coroutines.CancellationException

/**
 * Reference product list with loading, empty, error and client-side search
 * states. Search filters the loaded page by name and description.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductListScreen(
    api: ApiClient,
    onOpenProduct: (Long) -> Unit,
    onCreateProduct: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var products by remember { mutableStateOf<List<Product>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var reloadToken by remember { mutableIntStateOf(0) }
    val components = LocalAppComponents.current

    LaunchedEffect(reloadToken) {
        loading = true
        error = null
        try {
            products = api.products()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.userMessage()
        } finally {
            loading = false
        }
    }

    val visible = remember(products, query) {
        val needle = query.trim()
        if (needle.isEmpty()) {
            products
        } else {
            products.filter { product ->
                product.name.contains(needle, ignoreCase = true) ||
                    product.description.contains(needle, ignoreCase = true)
            }
        }
    }
    val currentError = error

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("Products", modifier = Modifier.semantics { heading() }) },
                actions = {
                    IconButton(onClick = { reloadToken += 1 }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Reload products")
                    }
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onCreateProduct,
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("New product") },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                singleLine = true,
                label = { Text("Search") },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            )
            when {
                loading -> LoadingState()
                currentError != null -> ErrorState(
                    message = currentError,
                    onRetry = { reloadToken += 1 },
                )
                visible.isEmpty() -> components.emptyState(
                    if (query.isBlank()) "No products yet" else "No matches",
                    if (query.isBlank()) {
                        "Create the first product to populate this reference slice."
                    } else {
                        "Try a different search term."
                    },
                )
                else -> ProductCollection(
                    products = visible,
                    onOpenProduct = onOpenProduct,
                )
            }
        }
    }
}

@Composable
private fun ProductCollection(
    products: List<Product>,
    onOpenProduct: (Long) -> Unit,
) {
    val components = LocalAppComponents.current
    if (currentLayoutMode() == LayoutMode.Compact) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 88.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(products, key = { it.id }) { product ->
                components.productCard(product) { onOpenProduct(product.id) }
            }
        }
    } else {
        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 260.dp),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 88.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            gridItems(products, key = { it.id }) { product ->
                components.productCard(product) { onOpenProduct(product.id) }
            }
        }
    }
}
