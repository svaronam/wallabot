package com.svaronam.wallabot

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Ajustes guardados en el móvil y llamadas HTTP al bot. */
class Prefs(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("wallabot", Context.MODE_PRIVATE)

    var server: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit().putString("server", v.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    /** Último aviso recibido. -1 = sin sincronizar (no se enseña el histórico al conectar). */
    var lastId: Long
        get() = sp.getLong("last_id", -1L)
        set(v) = sp.edit().putLong("last_id", v).apply()

    var askedBattery: Boolean
        get() = sp.getBoolean("asked_battery", false)
        set(v) = sp.edit().putBoolean("asked_battery", v).apply()

    val configured: Boolean get() = server.isNotBlank()

    fun panelUrl(): String {
        val t = if (token.isNotBlank()) "?token=" + URLEncoder.encode(token, "UTF-8") else ""
        return "$server/$t"
    }
}

object Http {
    fun request(
        prefs: Prefs, path: String, method: String = "GET", body: String? = null,
        timeoutMs: Int = 15000,
    ): JSONObject {
        val conn = URL(prefs.server + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 10000
            conn.readTimeout = timeoutMs
            conn.setRequestProperty("Accept", "application/json")
            if (prefs.token.isNotBlank()) conn.setRequestProperty("X-Token", prefs.token)
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code == 401) throw IllegalStateException("Token incorrecto")
            if (code !in 200..299) throw IllegalStateException("HTTP $code")
            return if (text.trim().startsWith("{")) JSONObject(text) else JSONObject().put("data", text)
        } finally {
            conn.disconnect()
        }
    }
}
