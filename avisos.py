#!/usr/bin/env python3
"""Envía por Telegram los avisos de los títulos marcados con «Recordarme».

Variables de entorno (secretos de GitHub):
  FIREBASE_SERVICE_ACCOUNT  contenido del JSON de la cuenta de servicio de Firebase
  FIREBASE_UID              tu identificador de usuario de Firebase
  TELEGRAM_BOT_TOKEN        clave de tu bot de Telegram
  TELEGRAM_CHAT_ID          tu identificador de chat de Telegram
  PANEL_URL                 (opcional) dirección del panel

Uso:
  python avisos.py            revisa los recordatorios y envía los avisos
  python avisos.py --prueba   solo envía un mensaje de prueba por Telegram
"""
import argparse
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = timezone.utc

RAIZ = Path(__file__).parent
PLATAFORMAS = {"netflix": "Netflix", "prime": "Prime Video", "disney": "Disney+", "hbo": "HBO Max"}
PANEL_URL = os.environ.get("PANEL_URL", "https://onofer.github.io/PelisySeries/")


def telegram(texto):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Faltan TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID")
    datos = urllib.parse.urlencode({"chat_id": chat, "text": texto, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def conectar():
    import firebase_admin
    from firebase_admin import credentials, firestore
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"]))
    firebase_admin.initialize_app(cred)
    return firestore.client()


def ruta(uid, doc):
    return f"usuarios/{uid}/datos/{doc}"


def leer_recordatorios(db, uid):
    snap = db.document(ruta(uid, "estado")).get()
    if not snap.exists:
        return set()
    estado = json.loads((snap.to_dict() or {}).get("json", "{}"))
    return {k for k, v in (estado.get("r") or {}).items() if v.get("v")}


def leer_avisos(db, uid):
    snap = db.document(ruta(uid, "avisos")).get()
    return dict(snap.to_dict() or {}) if snap.exists else {}


def guardar_avisos(db, uid, avisos):
    db.document(ruta(uid, "avisos")).set(avisos)


def decidir(items, recordatorios, avisados, hoy):
    """Devuelve {clave: (título, tipo)} con lo que hay que avisar hoy."""
    res = {}
    for it in items:
        k = str(it.get("id") or it["titulo"])
        if k not in recordatorios or k in avisados:
            continue
        if it["estado"] == "new":
            tipo = "disponible"
        elif it["estado"] == "upcoming" and it["fecha"] == hoy:
            tipo = "hoy"
        elif it["estado"] == "upcoming" and it["fecha"] < hoy:
            tipo = "disponible"
        else:
            continue
        if k not in res or tipo == "disponible":
            res[k] = (it, tipo)
    return res


def mensaje(it, tipo):
    p = PLATAFORMAS.get(it["plataforma"], it["plataforma"])
    t = html.escape(it["titulo"])
    cab = f"🔔 Hoy llega a {p}: <b>{t}</b>" if tipo == "hoy" else f"🎬 Ya disponible en {p}: <b>{t}</b>"
    det = ("Serie" if it.get("tipo") == "s" else "Película") + (f", {it['genero']}" if it.get("genero") else "")
    if it.get("imdb") is not None:
        det += f", ★ {it['imdb']:.1f}"
    sin = (it.get("sinopsis") or "").strip()
    if len(sin) > 220:
        sin = sin[:217].rsplit(" ", 1)[0] + "…"
    partes = [cab, html.escape(det)]
    if sin:
        partes.append(html.escape(sin))
    partes.append(f'<a href="{PANEL_URL}">Abrir el panel</a>')
    return "\n".join(partes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prueba", action="store_true")
    args = ap.parse_args()

    if args.prueba:
        telegram("✅ Prueba correcta: el bot de Pelis y Series puede escribirte.")
        print("Mensaje de prueba enviado")
        return

    uid = os.environ.get("FIREBASE_UID")
    if not uid:
        sys.exit("Falta FIREBASE_UID")
    datos = json.loads((RAIZ / "data.json").read_text(encoding="utf-8"))
    hoy = datetime.now(TZ).date().isoformat()
    db = conectar()
    rec = leer_recordatorios(db, uid)
    avisados = {k: v for k, v in leer_avisos(db, uid).items() if k in rec}
    pendientes = decidir(datos.get("items", []), rec, avisados, hoy)
    enviados = 0
    try:
        for k, (it, tipo) in pendientes.items():
            telegram(mensaje(it, tipo))
            avisados[k] = hoy
            enviados += 1
    finally:
        guardar_avisos(db, uid, avisados)
    print(f"{len(rec)} recordatorios activos, {enviados} avisos enviados")


if __name__ == "__main__":
    main()
