package com.example.android.core.ui

import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.window.core.layout.WindowWidthSizeClass
import org.junit.Assert.assertEquals
import org.junit.Test

class AdaptiveTest {
    @Test
    fun mapsWidthClassesToLayoutModes() {
        assertEquals(LayoutMode.Compact, layoutModeFor(WindowWidthSizeClass.COMPACT))
        assertEquals(LayoutMode.Medium, layoutModeFor(WindowWidthSizeClass.MEDIUM))
        assertEquals(LayoutMode.Expanded, layoutModeFor(WindowWidthSizeClass.EXPANDED))
    }

    @Test
    fun mapsLayoutModesToNavigationSurfaces() {
        assertEquals(
            NavigationSuiteType.NavigationBar,
            navigationSuiteTypeFor(LayoutMode.Compact),
        )
        assertEquals(
            NavigationSuiteType.NavigationRail,
            navigationSuiteTypeFor(LayoutMode.Medium),
        )
        assertEquals(
            NavigationSuiteType.NavigationDrawer,
            navigationSuiteTypeFor(LayoutMode.Expanded),
        )
    }
}
