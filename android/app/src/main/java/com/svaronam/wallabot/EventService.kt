package com.svaronam.wallabot

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Servicio en primer plano que mantiene una conexión "long-poll" con el bot de la Raspberry
 * a través de Tailscale. El bot responde en cuanto tiene un aviso nuevo, así que llegan al momento.
 */
class EventService : Service() {

    companion object {
        private const val DOWN_AFTER_MS = 10 * 60 * 1000L   // aviso de "sin conexión" tras 10 min
        private const val MAX_SHOWN_PER_BATCH = 8

        @Volatile var connected = false
            private set

        fun start(ctx: Context) {
            if (!Prefs(ctx).configured) return
            ContextCompat.startForegroundService(ctx, Intent(ctx, EventService::class.java))
        }

        fun restart(ctx: Context) {
            ctx.stopService(Intent(ctx, EventService::class.java))
            start(ctx)
        }
    }

    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifier.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val n = Notifier.ongoing(this, "Conectando con el bot…")
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, Notifier.ID_ONGOING, n, type)
        if (!running) {
            running = true
            worker = Thread({ loop() }, "wallabot-events").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        connected = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun loop() {
        val prefs = Prefs(this)
        var backoff = 2000L
        var failingSince = 0L
        var downShown = false
        var lastState = ""
        val hhmm = SimpleDateFormat("HH:mm", Locale.getDefault())

        fun state(text: String) {
            if (text != lastState) {
                lastState = text
                Notifier.updateOngoing(this, text)
            }
        }

        while (running) {
            if (!prefs.configured) {
                state("Configura la dirección del bot en la app")
                sleep(30000)
                continue
            }
            try {
                if (prefs.lastId < 0) {
                    // primera conexión: se empieza desde ahora, sin volcar el histórico
                    prefs.lastId = Http.request(prefs, "/api/events?after=0&limit=1").optLong("latest", 0)
                }
                val r = Http.request(prefs, "/api/events?after=${prefs.lastId}&wait=50&limit=100", timeoutMs = 75000)
                val evs = r.optJSONArray("events")
                val count = evs?.length() ?: 0
                if (count > 0) {
                    val start = maxOf(0, count - MAX_SHOWN_PER_BATCH)
                    if (start > 0) {
                        Notifier.simple(this, 3, "Wallabot", "Tienes $count avisos nuevos. Ábrelos en el panel.")
                    }
                    for (i in start until count) Notifier.show(this, evs!!.getJSONObject(i))
                    prefs.lastId = evs!!.getJSONObject(count - 1).optLong("id", prefs.lastId)
                }
                val latest = r.optLong("latest", prefs.lastId)
                if (latest < prefs.lastId) prefs.lastId = latest   // la base de datos del bot se ha reiniciado

                connected = true
                failingSince = 0L
                backoff = 2000L
                if (downShown) {
                    Notifier.cancel(this, Notifier.ID_DOWN)
                    downShown = false
                }
                if (count > 0) state("Conectado · último aviso ${hhmm.format(Date())}")
                else if (!lastState.startsWith("Conectado")) state("Conectado al bot")
            } catch (e: Exception) {
                if (!running) break
                connected = false
                val now = System.currentTimeMillis()
                if (failingSince == 0L) failingSince = now
                state("Sin conexión con el bot · reintentando")
                if (!downShown && now - failingSince > DOWN_AFTER_MS) {
                    downShown = true
                    Notifier.simple(
                        this, Notifier.ID_DOWN, "No llego al bot",
                        "Hace más de 10 minutos que no responde (${e.message ?: e.javaClass.simpleName}). " +
                            "¿Está encendida la Raspberry y Tailscale activo en el móvil?",
                    )
                }
                sleep(backoff)
                backoff = minOf(backoff * 2, 60000L)
            }
        }
    }

    private fun sleep(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
        }
    }
}
