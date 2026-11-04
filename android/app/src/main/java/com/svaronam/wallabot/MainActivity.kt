package com.svaronam.wallabot

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.Menu
import android.view.MenuItem
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/** Pantalla principal: el panel del bot dentro de la app + ajustes de conexión. */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var web: WebView
    private val main = Handler(Looper.getMainLooper())

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        Notifier.createChannels(this)

        web = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webChromeClient = WebChromeClient()  // para los avisos y confirmaciones del panel
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                    val url = req.url
                    val bot = Uri.parse(prefs.server)
                    if (url.host == bot.host && url.port == bot.port) return false
                    // enlaces a Wallapop: se abren en su app (o en el navegador)
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, url))
                    } catch (_: Exception) {
                    }
                    return true
                }

                override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                    if (req.isForMainFrame) showOffline(err.description?.toString() ?: "error de red")
                }
            }
        }
        setContentView(web)

        askNotificationPermission()
        if (!prefs.configured) settingsDialog(first = true) else {
            load()
            EventService.start(this)
            askBatteryOnce()
        }
    }

    override fun onResume() {
        super.onResume()
        if (prefs.configured) EventService.start(this)
    }

    private fun load() {
        if (prefs.configured) web.loadUrl(prefs.panelUrl())
    }

    private fun showOffline(reason: String) {
        val html = """
            <html><body style="font-family:sans-serif;padding:24px;color:#444">
            <h3>No llego al bot</h3>
            <p>$reason</p>
            <p>Comprueba que Tailscale está activo en el móvil y que la Raspberry está encendida.</p>
            <p>Dirección: <b>${prefs.server}</b></p>
            <p>Pulsa ⋮ → Recargar para reintentar.</p></body></html>
        """.trimIndent()
        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    // ------------------------------------------------------------------ menú
    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Recargar")
        menu.add(0, 2, 1, "Probar notificación")
        menu.add(0, 3, 2, "Ajustes de conexión")
        menu.add(0, 4, 3, "Canales de notificación")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> load()
            2 -> background("Enviando prueba…") {
                Http.request(prefs, "/api/test-notification", "POST", "{}")
                "Prueba enviada: debería llegar en unos segundos"
            }
            3 -> settingsDialog(first = false)
            4 -> startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            )
        }
        return true
    }

    // ------------------------------------------------------------------ ajustes
    private fun settingsDialog(first: Boolean) {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
        }
        box.addView(TextView(this).apply {
            text = "Dirección del bot por Tailscale, por ejemplo http://homelab1:8788"
        })
        val url = EditText(this).apply {
            hint = "http://homelab1:8788"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(prefs.server.ifBlank { "http://homelab1:8788" })
        }
        box.addView(url)
        box.addView(TextView(this).apply { text = "Token (WALLABOT_TOKEN del fichero .env; vacío si no pusiste)" })
        val tok = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(prefs.token)
        }
        box.addView(tok)

        AlertDialog.Builder(this)
            .setTitle(if (first) "Conectar con el bot" else "Ajustes de conexión")
            .setView(box)
            .setCancelable(!first)
            .setPositiveButton("Guardar") { _, _ ->
                var u = url.text.toString().trim()
                if (u.isNotEmpty() && !u.startsWith("http")) u = "http://$u"
                prefs.server = u
                prefs.token = tok.text.toString()
                prefs.lastId = -1
                background("Probando conexión…") {
                    val st = Http.request(prefs, "/api/status")
                    "Conectado: ${st.optInt("searches")} búsquedas activas"
                }
                load()
                EventService.restart(this)
                askBatteryOnce()
            }
            .apply { if (!first) setNegativeButton("Cancelar", null) }
            .show()
    }

    private fun background(start: String, job: () -> String) {
        Toast.makeText(this, start, Toast.LENGTH_SHORT).show()
        Thread {
            val msg = try {
                job()
            } catch (e: Exception) {
                "Error: ${e.message ?: e.javaClass.simpleName}"
            }
            main.post { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
        }.start()
    }

    // ------------------------------------------------------------------ permisos
    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 10)
        }
    }

    /** Sin esto Android corta la conexión con el móvil en reposo y los avisos llegan tarde. */
    @SuppressLint("BatteryLife")
    private fun askBatteryOnce() {
        val pm = getSystemService(PowerManager::class.java)
        if (prefs.askedBattery || pm.isIgnoringBatteryOptimizations(packageName)) return
        prefs.askedBattery = true
        AlertDialog.Builder(this)
            .setTitle("Avisos al momento")
            .setMessage("Para que los avisos lleguen aunque el móvil esté en reposo, permite que Wallabot no tenga restricciones de batería. Gasta muy poco: es una conexión en espera.")
            .setPositiveButton("Permitir") { _, _ ->
                try {
                    startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
                } catch (_: Exception) {
                }
            }
            .setNegativeButton("Ahora no", null)
            .show()
    }
}
