package com.example.android.core.ui

import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.currentWindowAdaptiveInfo
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.compose.runtime.Composable
import androidx.window.core.layout.WindowWidthSizeClass

/** The three width classes the shell and grids respond to. */
enum class LayoutMode {
    Compact,
    Medium,
    Expanded,
}

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
fun currentLayoutMode(): LayoutMode =
    when (currentWindowAdaptiveInfo().windowSizeClass.windowWidthSizeClass) {
        WindowWidthSizeClass.COMPACT -> LayoutMode.Compact
        WindowWidthSizeClass.MEDIUM -> LayoutMode.Medium
        else -> LayoutMode.Expanded
    }

/**
 * Navigation surface for the current window: bottom bar on phones, rail on
 * medium widths and a permanent drawer on expanded widths.
 */
@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
fun rememberNavigationSuiteType(): NavigationSuiteType =
    when (currentLayoutMode()) {
        LayoutMode.Compact -> NavigationSuiteType.NavigationBar
        LayoutMode.Medium -> NavigationSuiteType.NavigationRail
        LayoutMode.Expanded -> NavigationSuiteType.NavigationDrawer
    }
