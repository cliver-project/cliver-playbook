package com.example.android.core.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.example.android.core.model.Product
import java.util.Locale

/**
 * The project's Android UI seam. Feature screens read this through
 * [LocalAppComponents]; replace a slot with your own composable without
 * touching screen state or data flow.
 */
@Immutable
data class AppComponents(
    val productCard: @Composable (Product, () -> Unit) -> Unit,
    val emptyState: @Composable (String, String?) -> Unit,
    val primaryButton: @Composable (String, () -> Unit) -> Unit,
    val chatMessage: @Composable (Boolean, String) -> Unit,
    val composer: @Composable (String, Boolean, (String) -> Unit, () -> Unit, () -> Unit) -> Unit,
    val toolCall: @Composable (String, String) -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
val ReferenceAppComponents = AppComponents(
    productCard = { product, onClick ->
        Card(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = product.name,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (product.description.isNotBlank()) {
                    Text(
                        text = product.description,
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = String.format(Locale.US, "%.2f", product.priceCents / 100.0),
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    },
    emptyState = { title, detail ->
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(text = title, style = MaterialTheme.typography.titleMedium)
            if (detail != null) {
                Text(
                    text = detail,
                    style = MaterialTheme.typography.bodyMedium,
                    textAlign = TextAlign.Center,
                )
            }
        }
    },
    primaryButton = { label, action ->
        Button(onClick = action) { Text(label) }
    },
    chatMessage = { fromUser, text ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = if (fromUser) Arrangement.End else Arrangement.Start,
        ) {
            Card(
                modifier = Modifier.fillMaxWidth(if (fromUser) 0.8f else 0.9f),
            ) {
                Text(
                    text = text,
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    },
    composer = { text, busy, onChange, send, stop ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = text,
                onValueChange = onChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                label = { Text("Ask a question") },
            )
            Button(
                onClick = if (busy) stop else send,
                enabled = busy || text.isNotBlank(),
            ) {
                Text(if (busy) "Stop" else "Send")
            }
        }
    },
    toolCall = { name, detail ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(text = name, style = MaterialTheme.typography.labelLarge)
                if (detail.isNotBlank()) {
                    Text(
                        text = detail,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    },
)

val LocalAppComponents = staticCompositionLocalOf { ReferenceAppComponents }
