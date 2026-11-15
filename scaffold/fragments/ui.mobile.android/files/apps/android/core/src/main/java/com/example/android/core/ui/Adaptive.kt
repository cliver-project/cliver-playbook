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

/** Pure width-class mapping so tablet/foldable layouts stay unit-testable. */
fun layoutModeFor(widthSizeClass: WindowWidthSizeClass): LayoutMode =
    when (widthSizeClass) {
        WindowWidthSizeClass.COMPACT -> LayoutMode.Compact
        WindowWidthSizeClass.MEDIUM -> LayoutMode.Medium
        else -> LayoutMode.Expanded
    }

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
fun currentLayoutMode(): LayoutMode =
    layoutModeFor(currentWindowAdaptiveInfo().windowSizeClass.windowWidthSizeClass)

/**
 * Navigation surface for the current window: bottom bar on phones, rail on
 * medium widths and a permanent drawer on expanded widths.
 */
/** Bottom bar on phones, rail on tablets, drawer on expanded/foldable widths. */
fun navigationSuiteTypeFor(mode: LayoutMode): NavigationSuiteType =
    when (mode) {
        LayoutMode.Compact -> NavigationSuiteType.NavigationBar
        LayoutMode.Medium -> NavigationSuiteType.NavigationRail
        LayoutMode.Expanded -> NavigationSuiteType.NavigationDrawer
    }

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
fun rememberNavigationSuiteType(): NavigationSuiteType =
    navigationSuiteTypeFor(currentLayoutMode())
