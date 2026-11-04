package com.svaronam.wallabot

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Crea los canales y pinta cada aviso del bot como notificación con foto. */
object Notifier {
    const val CH_SERVICE = "servicio"
    const val ID_ONGOING = 1
    const val ID_DOWN = 2

    // canal, nombre visible, importancia
    private val CHANNELS = listOf(
        Triple("chollo", "🔥 Chollos", NotificationManager.IMPORTANCE_HIGH),
        Triple("reactivado", "↩️ Reservados que se liberan", NotificationManager.IMPORTANCE_HIGH),
        Triple("nuevo", "🆕 Anuncios nuevos", NotificationManager.IMPORTANCE_DEFAULT),
        Triple("bajada", "📉 Bajadas de precio", NotificationManager.IMPORTANCE_DEFAULT),
        Triple("oportunidad", "⏱️ Prisa y republicados", NotificationManager.IMPORTANCE_DEFAULT),
        Triple("mercado", "✅ Vendidos y reservados", NotificationManager.IMPORTANCE_LOW),
        Triple("resumen", "📊 Resumen diario", NotificationManager.IMPORTANCE_LOW),
        Triple("sistema", "⚙️ Estado del bot", NotificationManager.IMPORTANCE_DEFAULT),
        Triple(CH_SERVICE, "Conexión en segundo plano", NotificationManager.IMPORTANCE_MIN),
    )

    fun channelFor(type: String): String = when (type) {
        "chollo" -> "chollo"
        "reactivado" -> "reactivado"
        "nuevo" -> "nuevo"
        "bajada" -> "bajada"
        "urgente", "republicado" -> "oportunidad"
        "vendido", "reservado" -> "mercado"
        "resumen" -> "resumen"
        else -> "sistema"
    }

    /** Icono pequeño y color de acento de cada tipo de aviso (generados por tools/icons.py). */
    fun iconFor(type: String): Int = when (type) {
        "chollo" -> R.drawable.ic_n_chollo
        "nuevo" -> R.drawable.ic_n_nuevo
        "bajada" -> R.drawable.ic_n_bajada
        "reactivado" -> R.drawable.ic_n_reactivado
        "reservado" -> R.drawable.ic_n_reservado
        "republicado" -> R.drawable.ic_n_republicado
        "urgente" -> R.drawable.ic_n_urgente
        "vendido" -> R.drawable.ic_n_vendido
        "resumen" -> R.drawable.ic_n_resumen
        "riesgo" -> R.drawable.ic_n_riesgo
        else -> R.drawable.ic_n_sistema
    }

    fun colorFor(type: String): Int = when (type) {
        "chollo" -> 0xFFE8590C.toInt()
        "nuevo" -> 0xFF2A78D6.toInt()
        "bajada" -> 0xFF0F8A6C.toInt()
        "reactivado" -> 0xFF7048E8.toInt()
        "reservado" -> 0xFF868E96.toInt()
        "republicado" -> 0xFF1098AD.toInt()
        "urgente" -> 0xFFF08C00.toInt()
        "vendido" -> 0xFF5C940D.toInt()
        "resumen" -> 0xFF1C7ED6.toInt()
        "riesgo" -> 0xFFE03131.toInt()
        else -> 0xFF495057.toInt()
    }

    /** Si el bot marcó riesgo (vendedor sin valoraciones, precio absurdo…), manda el icono de aviso. */
    private fun hasRisk(ev: JSONObject): Boolean = try {
        val raw = ev.optString("extra")
        raw.startsWith("{") && (JSONObject(raw).optJSONArray("risk")?.length() ?: 0) > 0
    } catch (_: Exception) {
        false
    }

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        for ((id, name, imp) in CHANNELS) {
            val ch = NotificationChannel(id, name, imp)
            if (id == CH_SERVICE) ch.setShowBadge(false)
            nm.createNotificationChannel(ch)
        }
    }

    private fun canPost(ctx: Context) = NotificationManagerCompat.from(ctx).areNotificationsEnabled()

    fun ongoing(ctx: Context, text: String) = NotificationCompat.Builder(ctx, CH_SERVICE)
        .setSmallIcon(R.drawable.ic_stat)
        .setColor(0xFF0F8A6C.toInt())
        .setContentTitle("Wallabot")
        .setContentText(text)
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setSilent(true)
        .setContentIntent(openApp(ctx))
        .build()

    fun updateOngoing(ctx: Context, text: String) {
        if (!canPost(ctx)) return
        try {
            NotificationManagerCompat.from(ctx).notify(ID_ONGOING, ongoing(ctx, text))
        } catch (_: SecurityException) {
        }
    }

    fun openApp(ctx: Context): PendingIntent = PendingIntent.getActivity(
        ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    fun simple(ctx: Context, id: Int, title: String, text: String, channel: String = "sistema") {
        if (!canPost(ctx)) return
        val n = NotificationCompat.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_n_sistema)
            .setColor(colorFor("sistema"))
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(openApp(ctx))
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(id, n)
        } catch (_: SecurityException) {
        }
    }

    fun cancel(ctx: Context, id: Int) = NotificationManagerCompat.from(ctx).cancel(id)

    /** Muestra un aviso del bot. Se llama desde un hilo de fondo (descarga la foto). */
    fun show(ctx: Context, ev: JSONObject) {
        if (!canPost(ctx)) return
        val eid = ev.optLong("id")
        val type = ev.optString("type")
        // el icono ya dice qué tipo de aviso es: se quita el emoji del principio del título
        val title = ev.optString("title").replace(Regex("^\\p{So}\\uFE0F?\\s*"), "")
        val body = ev.optString("body")
        val url = ev.optString("url").takeIf { it.isNotBlank() && it != "null" }
        val itemId = ev.optString("item_id").takeIf { it.isNotBlank() && it != "null" }
        val image = ev.optString("image").takeIf { it.isNotBlank() && it != "null" }
        val firstLine = body.lineSequence().firstOrNull() ?: ""
        val notifId = (1000 + eid % 1_000_000).toInt()

        val tap = if (url != null) {
            PendingIntent.getActivity(
                ctx, notifId, Intent(Intent.ACTION_VIEW, Uri.parse(url)),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        } else openApp(ctx)

        val look = if (hasRisk(ev)) "riesgo" else type
        val b = NotificationCompat.Builder(ctx, channelFor(type))
            .setSmallIcon(iconFor(look))
            .setColor(colorFor(look))
            .setContentTitle(title)
            .setContentText(firstLine)
            .setContentIntent(tap)
            .setAutoCancel(true)
            .setWhen((ev.optDouble("ts", System.currentTimeMillis() / 1000.0) * 1000).toLong())
            .setShowWhen(true)
            .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)

        val bmp = image?.let { downloadBitmap(it) }
        if (bmp != null) {
            b.setLargeIcon(bmp)
            b.setStyle(
                NotificationCompat.BigPictureStyle()
                    .bigPicture(bmp)
                    .bigLargeIcon(null as Bitmap?)
                    .setSummaryText(body.replace("\n", " · "))
            )
        } else {
            b.setStyle(NotificationCompat.BigTextStyle().bigText(body))
        }

        if (itemId != null) {
            val follow = Intent(ctx, ActionReceiver::class.java)
                .setAction(ActionReceiver.ACTION_FOLLOW)
                .putExtra(ActionReceiver.EXTRA_ITEM, itemId)
            b.addAction(
                0, "☆ Seguir",
                PendingIntent.getBroadcast(
                    ctx, notifId, follow,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
        }
        b.addAction(0, "Panel", openApp(ctx))

        try {
            NotificationManagerCompat.from(ctx).notify(notifId, b.build())
        } catch (_: SecurityException) {
        }
    }

    private fun downloadBitmap(src: String): Bitmap? = try {
        val conn = URL(src).openConnection() as HttpURLConnection
        conn.connectTimeout = 8000
        conn.readTimeout = 12000
        conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Android) Wallabot")
        val bytes = conn.inputStream.use { it.readBytes() }
        conn.disconnect()
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (bounds.outWidth / sample > 1080 || bounds.outHeight / sample > 1080) sample *= 2
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
    } catch (_: Exception) {
        null
    }
}
