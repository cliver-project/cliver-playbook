package com.example.android.core.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val LightColors = lightColorScheme(
    primary = Color(0xFF2F5D8A),
    secondary = Color(0xFF4F6F52),
    tertiary = Color(0xFF7A5C3E),
    error = Color(0xFFB3261E),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF9EC3EE),
    secondary = Color(0xFFB6D3B8),
    tertiary = Color(0xFFE4C29E),
    error = Color(0xFFF2B8B5),
)

/**
 * Material 3 theme. Dynamic colour is used on Android 12+ when available; the
 * static schemes keep the skeleton recognisable on older devices. Dark mode
 * follows the system setting.
 */
@Composable
fun PlaybookTheme(
    components: AppComponents = ReferenceAppComponents,
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
    ) {
        CompositionLocalProvider(LocalAppComponents provides components, content = content)
    }
}
