import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.example.android.core"
    compileSdk = 35

    defaultConfig {
        minSdk = 26
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.01.00")
    api(project(":contracts"))
    api(composeBom)

    api("androidx.compose.ui:ui")
    api("androidx.compose.material3:material3")
    api("androidx.compose.material3.adaptive:adaptive:1.0.0")
    api("androidx.compose.material3:material3-adaptive-navigation-suite:1.3.1")
    api("androidx.window:window-core:1.3.0")
    api("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    api("com.squareup.okhttp3:okhttp:4.12.0")

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    testImplementation("junit:junit:4.13.2")
}
