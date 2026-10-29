#!/usr/bin/env python3
"""Genera data.json con las novedades de streaming en España para el panel.

Variables de entorno:
  SA_API_KEY    (obligatoria) clave de Streaming Availability API (Developers Platform, plan gratuito)
  SA_PLATAFORMA (opcional)    "developers" (por defecto) o "rapidapi", según dónde sacaste la clave
  TMDB_API_KEY  (opcional)    pósters, reparto con fotos, tráiler y textos en español
  OMDB_API_KEY  (opcional)    nota de Rotten Tomatoes

Uso:
  python actualizar_datos.py              genera data.json y cache.json
  python actualizar_datos.py --servicios  lista los servicios de España y sus ids
  python actualizar_datos.py --debug      enseña un cambio de ejemplo de la API
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = timezone.utc

PAIS = "es"
# id del servicio en la API -> clave que usa el panel
SERVICIOS = {"netflix": "netflix", "prime": "prime", "disney": "disney", "hbo": "hbo"}
PAGINAS = {"new": 4, "upcoming": 2, "expiring": 2}  # 25 cambios por página
DIAS_ATRAS = 14
MAX_TMDB = 60   # consultas nuevas a TMDB por ejecución
MAX_OMDB = 60   # consultas nuevas a OMDb por ejecución
MAX_TEMP = 40   # temporadas nuevas (episodios) a consultar por ejecución
SA_URL_DEV = "https://api.movieofthenight.com/v4"   # Developers Platform (cabecera X-API-Key)
SA_HOST_RAPID = "streaming-availability.p.rapidapi.com"  # RapidAPI (cabecera X-RapidAPI-Key)


def http_json(url, headers=None, intentos=3):
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and n < intentos - 1:
                time.sleep(5 * (n + 1))
                continue
            raise
        except urllib.error.URLError:
            if n < intentos - 1:
                time.sleep(3)
                continue
            raise


def sa_get(ruta, params):
    clave = os.environ.get("SA_API_KEY") or os.environ.get("RAPIDAPI_KEY")
    if not clave:
        sys.exit("Falta la variable de entorno SA_API_KEY")
    if os.environ.get("SA_PLATAFORMA", "developers").lower() == "rapidapi":
        base = f"https://{SA_HOST_RAPID}"
        cabeceras = {"X-RapidAPI-Key": clave, "X-RapidAPI-Host": SA_HOST_RAPID}
    else:
        base = SA_URL_DEV
        cabeceras = {"X-API-Key": clave}
    return http_json(f"{base}{ruta}?" + urllib.parse.urlencode(params), cabeceras)


def obtener_cambios(tipo):
    params = {"change_type": tipo, "service": ",".join(SERVICIOS),
              "country": PAIS, "item_type": "show"}
    if tipo == "new":
        params["order_direction"] = "desc"
        params["from"] = int((datetime.now(timezone.utc) - timedelta(days=DIAS_ATRAS)).timestamp())
    else:
        params["include_unknown_dates"] = "false"
    cambios, shows, cursor = [], {}, None
    for _ in range(PAGINAS[tipo]):
        if cursor:
            params["cursor"] = cursor
        d = sa_get("/changes", params)
        cambios += d.get("changes", [])
        shows.update(d.get("shows", {}))
        cursor = d.get("nextCursor")
        if not cursor:
            break
    return cambios, shows


def servicio_id(cambio):
    s = cambio.get("service")
    return (s.get("id") if isinstance(s, dict) else s) or ""


def fecha_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(TZ).date().isoformat()


def tmdb_ref(show):
    t = str(show.get("tmdbId") or "")
    if "/" in t:
        tipo, i = t.split("/", 1)
    else:
        tipo, i = ("movie" if show.get("showType") == "movie" else "tv"), t
    return (tipo, i) if i.isdigit() and tipo in ("movie", "tv") else (None, None)


def tmdb(tipo, i, cache, pres):
    k = f"{tipo}/{i}"
    if k in cache["tmdb"]:
        return cache["tmdb"][k]
    clave = os.environ.get("TMDB_API_KEY")
    if not clave or pres["tmdb"] <= 0:
        return {}
    pres["tmdb"] -= 1
    q = urllib.parse.urlencode({"api_key": clave, "language": "es-ES",
                                "append_to_response": "credits,videos",
                                "include_video_language": "es,en"})
    try:
        d = http_json(f"https://api.themoviedb.org/3/{k}?{q}")
    except Exception as e:
        print(f"AVISO: TMDB {k}: {e}", file=sys.stderr)
        return {}
    trailer = next((f"https://www.youtube.com/watch?v={v['key']}"
                    for v in d.get("videos", {}).get("results", [])
                    if v.get("site") == "YouTube" and v.get("type") == "Trailer"), None)
    reparto = [{"nombre": c["name"],
                "foto": "https://image.tmdb.org/t/p/w185" + c["profile_path"] if c.get("profile_path") else None}
               for c in d.get("credits", {}).get("cast", [])[:6]]
    res = {"titulo": d.get("title") or d.get("name"),
           "sinopsis": d.get("overview") or "",
           "poster": "https://image.tmdb.org/t/p/w342" + d["poster_path"] if d.get("poster_path") else None,
           "reparto": reparto, "trailer": trailer,
           "temporadas": d.get("number_of_seasons"),
           "episodios": d.get("number_of_episodes"),
           "minutos": d.get("runtime"),
           "generos": [g["name"] for g in d.get("genres", []) if g.get("name")],
           "nums_temp": [t["season_number"] for t in d.get("seasons", []) if t.get("season_number", 0) > 0]}
    cache["tmdb"][k] = res
    return res


def temporadas(i, numeros, cache, pres):
    """Episodios por temporada (TMDB). La última temporada se refresca cada 3 días."""
    clave = os.environ.get("TMDB_API_KEY")
    limite = (datetime.now() - timedelta(days=3)).date().isoformat()
    res = []
    for n in numeros:
        k = f"tv/{i}/s{n}"
        c = cache["temp"].get(k)
        if not c or (n == max(numeros) and c["fecha"] <= limite):
            if not clave or pres["temp"] <= 0:
                if c:
                    res.append({"n": n, "eps": c["eps"]})
                continue
            pres["temp"] -= 1
            q = urllib.parse.urlencode({"api_key": clave, "language": "es-ES"})
            try:
                d = http_json(f"https://api.themoviedb.org/3/tv/{i}/season/{n}?{q}")
            except Exception as e:
                print(f"AVISO: TMDB temporada {k}: {e}", file=sys.stderr)
                continue
            c = {"fecha": datetime.now().date().isoformat(),
                 "eps": [{"n": e["episode_number"], "t": e.get("name") or "", "f": e.get("air_date") or ""}
                         for e in d.get("episodes", [])]}
            cache["temp"][k] = c
        res.append({"n": n, "eps": c["eps"]})
    return res


def omdb_rt(imdb, cache, pres):
    clave = os.environ.get("OMDB_API_KEY")
    if not clave or not imdb:
        return None
    c = cache["omdb"].get(imdb)
    limite = (datetime.now() - timedelta(days=7)).date().isoformat()
    if c and (c["rt"] is not None or c["fecha"] > limite):
        return c["rt"]
    if pres["omdb"] <= 0:
        return c["rt"] if c else None
    pres["omdb"] -= 1
    try:
        d = http_json("https://www.omdbapi.com/?" + urllib.parse.urlencode({"apikey": clave, "i": imdb}))
    except Exception as e:
        print(f"AVISO: OMDb {imdb}: {e}", file=sys.stderr)
        return c["rt"] if c else None
    rt = None
    for r in d.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            try:
                rt = int(r["Value"].rstrip("%"))
            except ValueError:
                pass
    cache["omdb"][imdb] = {"rt": rt, "fecha": datetime.now().date().isoformat()}
    return rt


def duracion(tipo, temporadas, episodios, minutos):
    if tipo == "s":
        if not temporadas:
            return ""
        t = f"{temporadas} temporada" + ("s" if temporadas != 1 else "")
        return t + (f", {episodios} episodios" if episodios else "")
    if not minutos:
        return ""
    return f"{minutos // 60} h {minutos % 60:02d} min" if minutos >= 60 else f"{minutos} min"


def construir(cambio, show, estado, cache, pres):
    ts = cambio.get("timestamp")
    plat = SERVICIOS.get(servicio_id(cambio))
    if not ts or not show or not plat:
        return None
    tipo = "s" if show.get("showType") == "series" else "p"
    tt, ti = tmdb_ref(show)
    extra = tmdb(tt, ti, cache, pres) if tt else {}
    rating = show.get("rating")
    imdb = round(rating / 10, 1) if isinstance(rating, (int, float)) and rating > 0 else None
    poster = extra.get("poster")
    if not poster:
        vp = (show.get("imageSet") or {}).get("verticalPoster") or {}
        poster = vp.get("w240") or next(iter(vp.values()), None)
    reparto = extra.get("reparto") or [{"nombre": n, "foto": None} for n in (show.get("cast") or [])[:6]]
    rt = omdb_rt(show.get("imdbId"), cache, pres) if estado != "upcoming" else None
    generos = extra.get("generos") or [g["name"] for g in (show.get("genres") or []) if g.get("name")]
    temp_det = temporadas(ti, extra.get("nums_temp") or [], cache, pres) if tipo == "s" and tt == "tv" else []
    return {
        "id": show.get("id"),
        "titulo": extra.get("titulo") or show.get("title"),
        "tipo": tipo,
        "plataforma": plat,
        "estado": estado,                       # new | upcoming | expiring
        "fecha": fecha_iso(ts),                 # alta, estreno previsto o caducidad
        "genero": generos[0] if generos else "",
        "generos": generos,
        "imdb": imdb,
        "rt": rt,
        "duracion": duracion(tipo, extra.get("temporadas") or show.get("seasonCount"),
                             extra.get("episodios") or show.get("episodeCount"),
                             extra.get("minutos") or show.get("runtime")),
        "sinopsis": extra.get("sinopsis") or show.get("overview") or "",
        "poster": poster,
        "reparto": reparto,
        "trailer": extra.get("trailer"),
        "temporadas_det": temp_det,
    }


def cargar(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=str(Path(__file__).parent / "data.json"))
    ap.add_argument("--servicios", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.servicios:
        print(json.dumps(sa_get(f"/countries/{PAIS}", {}), indent=1, ensure_ascii=False))
        return

    salida = Path(args.salida)
    ruta_cache = salida.with_name("cache.json")
    cache = cargar(ruta_cache, {})
    if cache.get("v") != 2:  # formato nuevo: se rehace la caché de TMDB
        cache = {"v": 2, "omdb": cache.get("omdb", {})}
    cache.setdefault("tmdb", {})
    cache.setdefault("omdb", {})
    cache.setdefault("temp", {})
    previo = cargar(salida, {"items": []})
    pres = {"tmdb": MAX_TMDB, "omdb": MAX_OMDB, "temp": MAX_TEMP}

    items, fallos = {}, 0
    for estado in ("new", "upcoming", "expiring"):
        try:
            cambios, shows = obtener_cambios(estado)
        except Exception as e:
            fallos += 1
            print(f"AVISO: '{estado}' falló ({e}); se conserva lo anterior", file=sys.stderr)
            for it in previo.get("items", []):
                if it.get("estado") == estado:
                    items[(it["plataforma"], it["id"], estado)] = it
            continue
        if args.debug and cambios:
            print(json.dumps(cambios[0], indent=1, ensure_ascii=False))
            print(json.dumps(shows.get(cambios[0].get("showId")), indent=1, ensure_ascii=False)[:1500])
        for c in cambios:
            it = construir(c, shows.get(c.get("showId")), estado, cache, pres)
            if it and it["titulo"]:
                clave = (it["plataforma"], it["id"], estado)
                if clave not in items or it["fecha"] > items[clave]["fecha"]:
                    items[clave] = it

    if fallos == 3:
        sys.exit("No se pudo obtener ningún dato; no se modifica data.json")

    datos = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "pais": PAIS.upper(), "items": sorted(items.values(), key=lambda i: (i["estado"], i["fecha"]))}
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    ruta_cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(datos['items'])} títulos en {salida}")


if __name__ == "__main__":
    main()
