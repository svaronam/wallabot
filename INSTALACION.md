# Wallabot

Rastreador de Wallapop para la Raspberry Pi con avisos al móvil (APK propia) por Tailscale y estudio del mercado 24/7.

```
 Wallapop  ◄── búsquedas y fichas públicas ──  Raspberry Pi (homelab1:8788)
                                                 ├─ rastreador 24/7 + SQLite
                                                 ├─ panel web
                                                 └─ /api/events (long-poll)
                                                        ▲
                                         Tailscale      │  la APK espera ahí y el bot
                                                        │  responde en cuanto hay aviso
                                                 Móvil: APK Wallabot
```

No usa tu cuenta de Wallapop, así que no hay riesgo para ella. Es independiente del bot de republicar: otro servicio y otro puerto (8788) en la misma Pi.

## Avisos

| Aviso | Cuándo |
|---|---|
| 🔥 Chollo | Anuncio nuevo X % por debajo de la mediana de esa búsqueda (sonido de prioridad alta) |
| 🆕 Nuevo | Anuncio nuevo que cumple la búsqueda (foto, título, precio, ciudad, envío) |
| 📉 Bajada de precio | Un anuncio ya visto baja de precio (precio anterior → nuevo, % y precio inicial) |
| ↩️ Liberado | Un anuncio reservado vuelve a estar disponible (prioridad alta) |
| 🔁 Republicado | El mismo vendedor vuelve a subir el mismo artículo: señal de prisa |
| ⏱️ Prisa | La descripción dice «urge», «mudanza», «negociable», «acepto ofertas»… |
| ⚠️ Riesgo | En chollos: vendedor sin valoraciones, cuenta de menos de un mes o precio absurdamente bajo |
| ✅ Vendido / 🔒 Reservado | Opcional por búsqueda; siempre para los anuncios que **sigues** |
| 📊 Resumen diario | A las 21:00: nuevos, vendidos, precio mínimo y precio de venta de cada búsqueda |
| ⚙️ Estado | Wallapop bloquea peticiones, una búsqueda lleva 3 días sin resultados, y en el móvil: «No llego al bot» si la Pi deja de responder 10 minutos |

Cada tipo va en su canal de Android, así que puedes silenciar o cambiar el sonido de cada uno desde Ajustes → Notificaciones. Al tocar la notificación se abre el anuncio en la app de Wallapop. El botón **☆ Seguir** hace que ese anuncio se revise cada hora y te avise de cualquier cambio.

## Mercado

Además de las búsquedas con avisos, puedes crear búsquedas de tipo **mercado** (por ejemplo «ps5», «pokemon charizard», «iphone 13»). El bot las recorre cada 30 minutos (3 páginas), guarda cada anuncio y vuelve a mirar su ficha cada pocas horas. Así sabe cuándo se reserva, baja de precio o desaparece, y calcula:

- **Lo que más se vende**: ranking de búsquedas por ventas en 7 días y rotación (qué parte de la oferta salió en la semana).
- **Lo que se vende más rápido**: mediana de días hasta venderse.
- Precio pedido frente a **precio de venta real**, rango de venta habitual y rebaja media antes de vender.
- Gráfica de nuevos y vendidos de los últimos 14 días, palabras más repetidas en lo que se vende, los más baratos ahora mismo y los últimos vendidos.

«Vendido» incluye los anuncios que Wallapop marca como vendidos y los que desaparecen; la mayoría desaparecen al venderse. Las cifras ganan fiabilidad tras unos días de rastreo.

## Instalación en la Raspberry

Sube esta carpeta a la Pi (por `git clone` de tu repo o con `scp -r wallabot usuario@homelab1:~`) y:

```bash
cd ~/wallabot
bash deploy/install.sh
```

Instala dependencias, crea el servicio `wallabot`, genera un token y te muestra la dirección del panel y el token para la APK.

Comandos útiles:

```bash
journalctl -u wallabot -f          # ver lo que hace en directo
sudo systemctl restart wallabot    # reiniciar
nano ~/wallabot/server/.env        # ajustes (luego reiniciar)
```

Actualizar: copia los ficheros nuevos y vuelve a ejecutar `bash deploy/install.sh` (no borra datos ni cambia el token).

## La APK

La compila GitHub Actions. Sube la carpeta a un repo nuevo (por ejemplo `svaronam/wallabot`). En cada push que toque `android/`, la pestaña **Actions** genera `wallabot.apk` en «Artifacts». Si subes una etiqueta `v1.0.0`, además aparece en Releases para descargarla desde el móvil.

También puedes abrir `android/` en Android Studio y darle a Run.

Primera vez en el móvil:

1. Instala la APK y abre Wallabot.
2. Pon `http://homelab1:8788` y el token que te dio el instalador.
3. Acepta las notificaciones y **quita las restricciones de batería** (la app te lo pide). Sin esto, Android corta la conexión en reposo y los avisos llegan tarde.
4. Menú ⋮ → **Probar notificación**.

Tailscale tiene que estar activo en el móvil. La APK está firmada siempre con la misma clave (guardada en GitHub Secrets, ver «Firma de la APK»), así que las versiones nuevas se instalan encima sin perder ajustes.

## Consejos de uso

- Para avisos, intervalos de 3–5 minutos. Más rápido no compensa y puede hacer que Wallapop bloquee la IP de casa. El mínimo permitido son 2 minutos.
- Usa «Excluir» para quitar ruido: `caja, funda, roto, piezas, busco, compro`.
- Cuando creas o cambias una búsqueda, la primera pasada solo toma base y no te avisa de lo que ya existía.
- En una Pi 3 aguanta sin problema unas 20–30 búsquedas. Si ves avisos de bloqueo, sube `WALLABOT_REQUEST_GAP`.

## Si Wallapop cambia su API

Todo lo que habla con Wallapop está en `server/wallabot/wallapop.py`. El resto (avisos, mercado, APK) no depende de la forma de sus respuestas. `journalctl -u wallabot` mostrará `búsqueda HTTP 4xx` o errores de parseo.

## Pruebas

```bash
cd server && .venv/bin/python -m tests.test_bot
```

Simula Wallapop sin conexión y comprueba cada tipo de aviso, las estadísticas, la API y el long-poll de la APK.

## Firma de la APK

La clave de firma no está en el repositorio. GitHub Actions la recibe de dos secretos del repo (*Settings → Secrets and variables → Actions*):

| Secreto | Contenido |
|---|---|
| `KEYSTORE_BASE64` | el archivo de la clave en Base64 (`base64 -w0 archivo`) |
| `KEYSTORE_PASSWORD` | su contraseña |

Para compilar en local, deja el archivo de la clave en `android/keystore/wallabot.jks` (está en `.gitignore`) y define `KEYSTORE_PASSWORD` antes de lanzar Gradle.
