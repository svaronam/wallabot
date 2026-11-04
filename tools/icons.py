"""Genera los iconos de Wallabot desde una sola definición.

Salida:
  android/app/src/main/res/drawable/ic_n_*.xml   icono pequeño de cada tipo de aviso
  android/app/src/main/res/drawable/ic_stat.xml  icono del servicio (etiqueta)
  android/app/src/main/res/drawable/ic_launcher_*.xml + mipmap-anydpi-v26/ic_launcher.xml
  server/wallabot/static/icons.js                 los mismos iconos para el panel
  tools/preview.html                              hoja para revisarlos

Uso:  python tools/icons.py
Cada icono es una lista de trazos en una cuadrícula de 24×24. Android tiñe los iconos de
notificación de un solo color, así que todo se dibuja en blanco sólido o con líneas.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "android/app/src/main/res")


def F(d, evenodd=False):
    return {"d": d, "fill": True, "evenodd": evenodd}


def S(d, w=2.2):
    return {"d": d, "stroke": w}


def circle(cx, cy, r):
    return f"M{cx - r:.2f},{cy:.2f} a{r:.2f},{r:.2f} 0 1,0 {2 * r:.2f},0 a{r:.2f},{r:.2f} 0 1,0 {-2 * r:.2f},0 z"


def gear(cx=12, cy=12, teeth=8, ro=10, ri=7.6, hole=3.1):
    pts = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth
        w = math.pi / teeth
        for a, r in ((a0 - w * 0.62, ri), (a0 - w * 0.36, ro), (a0 + w * 0.36, ro), (a0 + w * 0.62, ri)):
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z " + circle(cx, cy, hole)
    return d


TAG = ("M3,12.6 V4.5 A1.5,1.5 0 0,1 4.5,3 H12.6 A1.5,1.5 0 0,1 13.66,3.44 L21.06,10.84 "
       "A1.5,1.5 0 0,1 21.06,12.96 L12.96,21.06 A1.5,1.5 0 0,1 10.84,21.06 L3.44,13.66 A1.5,1.5 0 0,1 3,12.6 Z "
       + circle(7.6, 7.6, 1.7))
LOCK_BODY = "M7,10.5 H17 A2,2 0 0,1 19,12.5 V19 A2,2 0 0,1 17,21 H7 A2,2 0 0,1 5,19 V12.5 A2,2 0 0,1 7,10.5 Z " + circle(12, 15.7, 1.6)

# tipo -> (nombre, color de acento, trazos)
ICONS = {
    "chollo": ("Chollo", "#E8590C", [
        F("M12.6,2 C13.2,5.6 10.6,7.3 9,9.4 C7.6,11.2 6.5,12.9 6.5,15.3 A5.5,5.5 0 0,0 17.5,15.3 "
          "C17.5,13 16.5,11.2 15,9.8 C15.1,11.5 14.4,12.7 13.2,13.2 C13.6,10.2 13.6,6 12.6,2 Z"),
    ]),
    "nuevo": ("Anuncio nuevo", "#2A78D6", [
        F("M11,3 L13,9.4 L19.5,11.5 L13,13.6 L11,20 L9,13.6 L2.5,11.5 L9,9.4 Z"),
        F("M18.5,1.8 L19.35,4.15 L21.7,5 L19.35,5.85 L18.5,8.2 L17.65,5.85 L15.3,5 L17.65,4.15 Z"),
    ]),
    "bajada": ("Bajada de precio", "#0F8A6C", [
        S("M3,6.5 L9,12.5 L13,8.5 L20.5,16"),
        S("M20.5,9.8 V16 H14.3"),
    ]),
    "reactivado": ("Reservado que se libera", "#7048E8", [
        F(LOCK_BODY, evenodd=True),
        S("M8.2,10.5 V7.3 A3.8,3.8 0 0,1 15.4,5.6", 2.1),
    ]),
    "reservado": ("Reservado", "#868E96", [
        F(LOCK_BODY, evenodd=True),
        S("M8.2,10.5 V7.6 A3.8,3.8 0 0,1 15.8,7.6 V10.5", 2.1),
    ]),
    "republicado": ("Republicado", "#1098AD", [
        S("M4,11.5 V9.5 A3,3 0 0,1 7,6.5 H19"),
        S("M16,3.5 L19,6.5 L16,9.5"),
        S("M20,12.5 V14.5 A3,3 0 0,1 17,17.5 H5"),
        S("M8,20.5 L5,17.5 L8,14.5"),
    ]),
    "urgente": ("Vende con prisa", "#F08C00", [
        S(circle(12, 13.5, 7.6)),
        S("M9.6,2.5 H14.4"),
        S("M12,9.3 V13.6 L14.8,15.6"),
        S("M18.6,5.8 L20,4.4", 2.0),
    ]),
    "vendido": ("Vendido", "#5C940D", [
        S(circle(12, 12, 9)),
        S("M7.6,12.4 L10.6,15.4 L16.6,9", 2.4),
    ]),
    "resumen": ("Resumen diario", "#1C7ED6", [
        F("M4,12.5 H7.5 V20 H4 Z M10.25,6 H13.75 V20 H10.25 Z M16.5,9 H20 V20 H16.5 Z"),
    ]),
    "sistema": ("Estado del bot", "#495057", [
        F(gear(), evenodd=True),
    ]),
    "riesgo": ("Posible estafa / vendedor de riesgo", "#E03131", [
        F("M12,2.6 C12.5,2.6 12.9,2.85 13.15,3.3 L22.2,19.1 C22.7,20 22.1,21 21.05,21 H2.95 "
          "C1.9,21 1.3,20 1.8,19.1 L10.85,3.3 C11.1,2.85 11.5,2.6 12,2.6 Z "
          "M10.9,8.6 H13.1 L12.75,14.6 H11.25 Z " + circle(12, 17.4, 1.25), evenodd=True),
    ]),
    "stat": ("Servicio (Wallabot)", "#0F8A6C", [F(TAG, evenodd=True)]),
}


def vector_xml(parts, size=24, color="#FFFFFFFF"):
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<!-- Generado por tools/icons.py: no editar a mano -->',
           f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="{size}dp" '
           f'android:height="{size}dp" android:viewportWidth="24" android:viewportHeight="24">']
    for p in parts:
        if p.get("fill"):
            ft = ' android:fillType="evenOdd"' if p.get("evenodd") else ""
            out.append(f'    <path android:fillColor="{color}"{ft} android:pathData="{p["d"]}" />')
        else:
            out.append(f'    <path android:strokeColor="{color}" android:strokeWidth="{p["stroke"]}" '
                       f'android:strokeLineCap="round" android:strokeLineJoin="round" android:pathData="{p["d"]}" />')
    out.append("</vector>")
    return "\n".join(out) + "\n"


def svg(parts, color="currentColor", size=24):
    els = []
    for p in parts:
        if p.get("fill"):
            fr = ' fill-rule="evenodd"' if p.get("evenodd") else ""
            els.append(f'<path fill="{color}"{fr} d="{p["d"]}"/>')
        else:
            els.append(f'<path fill="none" stroke="{color}" stroke-width="{p["stroke"]}" '
                       f'stroke-linecap="round" stroke-linejoin="round" d="{p["d"]}"/>')
    return f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">{"".join(els)}</svg>'


# ------------------------------------------------------------------ icono de la app
# Capa delantera de 108×108 (zona segura: círculo de 66 en el centro).
# Etiqueta de precio blanca + lupa amarilla: "rastrear precios".
LAUNCH_TAG = ("M30,55.5 V35 A5,5 0 0,1 35,30 H55.5 A5,5 0 0,1 59.04,31.46 L77.54,49.96 "
              "A5,5 0 0,1 77.54,57.04 L57.04,77.54 A5,5 0 0,1 49.96,77.54 L31.46,59.04 A5,5 0 0,1 30,55.5 Z "
              "M38.5,43 a4.5,4.5 0 1,0 9,0 a4.5,4.5 0 1,0 -9,0 z")
LENS_RING = "M56,64 a10.5,10.5 0 1,0 21,0 a10.5,10.5 0 1,0 -21,0 z M60.2,64 a6.3,6.3 0 1,0 12.6,0 a6.3,6.3 0 1,0 -12.6,0 z"
LENS_HALO = "M52.5,64 a14,14 0 1,0 28,0 a14,14 0 1,0 -28,0 z"
HANDLE = "M73.8,72.2 L80.6,79"


def launcher_fg(mono=False):
    w = "#FFFFFFFF"
    y = "#FFFFFFFF" if mono else "#FFFFD43B"
    halo = "" if mono else f'    <path android:fillColor="#FF0B7285" android:pathData="{LENS_HALO}" />\n'
    if mono:
        # en el icono temático la lupa se separa de la etiqueta con un hueco
        tag = f'    <path android:fillColor="{w}" android:fillType="evenOdd" android:pathData="{LAUNCH_TAG} {LENS_HALO}" />\n'
    else:
        tag = f'    <path android:fillColor="{w}" android:fillType="evenOdd" android:pathData="{LAUNCH_TAG}" />\n'
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Generado por tools/icons.py -->\n'
            '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" '
            'android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">\n'
            + tag + halo +
            f'    <path android:fillColor="{y}" android:fillType="evenOdd" android:pathData="{LENS_RING}" />\n'
            f'    <path android:strokeColor="{y}" android:strokeWidth="6" android:strokeLineCap="round" android:pathData="{HANDLE}" />\n'
            '</vector>\n')


LAUNCHER_BG = '''<?xml version="1.0" encoding="utf-8"?>
<!-- Generado por tools/icons.py -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:aapt="http://schemas.android.com/aapt"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <path android:pathData="M0,0h108v108h-108z">
        <aapt:attr name="android:fillColor">
            <gradient android:type="linear" android:startX="0" android:startY="0" android:endX="108" android:endY="108">
                <item android:offset="0" android:color="#FF12B886" />
                <item android:offset="1" android:color="#FF0B7285" />
            </gradient>
        </aapt:attr>
    </path>
</vector>
'''

ADAPTIVE = '''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_bg" />
    <foreground android:drawable="@drawable/ic_launcher_fg" />
    <monochrome android:drawable="@drawable/ic_launcher_mono" />
</adaptive-icon>
'''


def launcher_svg(size=192, shape="squircle"):
    clip = {"squircle": '<rect width="108" height="108" rx="26"/>', "circle": '<circle cx="54" cy="54" r="54"/>'}[shape]
    return f'''<svg viewBox="0 0 108 108" width="{size}" height="{size}"><defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#12B886"/><stop offset="1" stop-color="#0B7285"/></linearGradient>
<clipPath id="c{shape}">{clip}</clipPath></defs><g clip-path="url(#c{shape})"><rect width="108" height="108" fill="url(#g)"/>
<path fill="#fff" fill-rule="evenodd" d="{LAUNCH_TAG}"/><path fill="#0B7285" d="{LENS_HALO}"/>
<path fill="#FFD43B" fill-rule="evenodd" d="{LENS_RING}"/><path stroke="#FFD43B" stroke-width="6" stroke-linecap="round" d="{HANDLE}"/></g></svg>'''


def main():
    os.makedirs(os.path.join(RES, "drawable"), exist_ok=True)
    for key, (_, _, parts) in ICONS.items():
        name = "ic_stat" if key == "stat" else f"ic_n_{key}"
        with open(os.path.join(RES, "drawable", name + ".xml"), "w") as f:
            f.write(vector_xml(parts))
    with open(os.path.join(RES, "drawable", "ic_launcher_fg.xml"), "w") as f:
        f.write(launcher_fg())
    with open(os.path.join(RES, "drawable", "ic_launcher_mono.xml"), "w") as f:
        f.write(launcher_fg(mono=True))
    with open(os.path.join(RES, "drawable", "ic_launcher_bg.xml"), "w") as f:
        f.write(LAUNCHER_BG)
    with open(os.path.join(RES, "mipmap-anydpi-v26", "ic_launcher.xml"), "w") as f:
        f.write(ADAPTIVE)

    # para el panel web: mismos iconos y colores
    js = {k: {"name": v[0], "color": v[1], "svg": svg(v[2])} for k, v in ICONS.items() if k != "stat"}
    with open(os.path.join(ROOT, "server/wallabot/static/icons.js"), "w") as f:
        f.write("// Generado por tools/icons.py: no editar a mano\nwindow.WB_ICONS = "
                + json.dumps(js, ensure_ascii=False, indent=1) + ";\n")

    # hoja de revisión
    cards = "".join(
        f'<div class="c"><div class="sb" style="color:{c}">{svg(p, size=24)}</div>'
        f'<div class="big" style="background:{c}">{svg(p, "#fff", 40)}</div>'
        f'<div class="dk">{svg(p, "#fff", 24)}</div><b>{n}</b><code>{k}</code></div>'
        for k, (n, c, p) in ICONS.items())
    html = f'''<!doctype html><meta charset="utf-8"><title>Iconos Wallabot</title><style>
body{{font:14px system-ui;background:#f4f5f2;margin:0;padding:24px;color:#1d2320}}h2{{margin:8px 0 14px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
.c{{background:#fff;border:1px solid #e2e5df;border-radius:14px;padding:14px;display:flex;flex-direction:column;align-items:center;gap:8px}}
.big{{width:64px;height:64px;border-radius:50%;display:grid;place-items:center}}.sb,.dk{{display:grid;place-items:center;width:40px;height:40px;border-radius:10px}}
.dk{{background:#1b1f1d}}.row{{display:flex;gap:10px}}code{{color:#68716c;font-size:12px}}b{{text-align:center;font-size:13px}}
.apps{{display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;margin-bottom:28px}}.apps div{{text-align:center;color:#68716c;font-size:12px}}
</style><h2>Icono de la app</h2><div class="apps"><div>{launcher_svg(192)}<br>forma redondeada</div><div>{launcher_svg(192, "circle")}<br>forma circular</div><div>{launcher_svg(64)}<br>tamaño real</div><div>{launcher_svg(40, "circle")}<br>pequeño</div></div>
<h2>Iconos de notificación</h2><div class="g">{cards}</div>'''
    with open(os.path.join(ROOT, "tools/preview.html"), "w") as f:
        f.write(html)
    with open(os.path.join(ROOT, "tools/app_icon.svg"), "w") as f:
        f.write(launcher_svg(512).replace('width="512" height="512"', 'width="512" height="512" xmlns="http://www.w3.org/2000/svg"'))
    print("iconos generados:", len(ICONS))


if __name__ == "__main__":
    main()
