package com.example.android.core.auth

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Persistence seam for the bearer token. Swap for a Keystore implementation. */
interface TokenStore {
    fun read(): String?
    fun write(token: String)
    fun clear()
}

/**
 * Token storage backed by EncryptedSharedPreferences with an AES256-GCM key in
 * the Android Keystore. Writes commit synchronously so the token survives a
 * process death immediately after sign-in.
 */
class SecureTokenStore(context: Context) : TokenStore {
    private val appContext = context.applicationContext
    private val preferences = EncryptedSharedPreferences.create(
        appContext,
        FILE_NAME,
        MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    override fun read(): String? = preferences.getString(TOKEN_KEY, null)

    override fun write(token: String) {
        preferences.edit().putString(TOKEN_KEY, token).commit()
    }

    override fun clear() {
        preferences.edit().remove(TOKEN_KEY).commit()
    }

    private companion object {
        const val FILE_NAME = "session"
        const val TOKEN_KEY = "bearer_token"
    }
}
