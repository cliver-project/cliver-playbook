package com.example.android.core.ui

import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

private val apiDateFormatter = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.getDefault())

/** Formats an API timestamp for read-only display. */
fun formatApiDate(value: OffsetDateTime): String = value.format(apiDateFormatter)
