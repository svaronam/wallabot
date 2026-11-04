package com.svaronam.wallabot

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import org.json.JSONObject

/** Arranca la escucha de avisos al encender el móvil o al actualizar la app. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            try {
                EventService.start(ctx)
            } catch (_: Exception) {
            }
        }
    }
}

/** Botón "Seguir" de las notificaciones. */
class ActionReceiver : BroadcastReceiver() {
    companion object {
        const val ACTION_FOLLOW = "com.svaronam.wallabot.FOLLOW"
        const val EXTRA_ITEM = "item_id"
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != ACTION_FOLLOW) return
        val item = intent.getStringExtra(EXTRA_ITEM) ?: return
        val pending = goAsync()
        val app = ctx.applicationContext
        Thread {
            val msg = try {
                Http.request(Prefs(app), "/api/items/$item/follow", "POST", JSONObject().put("follow", true).toString())
                "Siguiendo. Te aviso de cualquier cambio en ese anuncio."
            } catch (e: Exception) {
                "No se pudo seguir: ${e.message}"
            }
            Handler(Looper.getMainLooper()).post {
                Toast.makeText(app, msg, Toast.LENGTH_LONG).show()
                pending.finish()
            }
        }.start()
    }
}
