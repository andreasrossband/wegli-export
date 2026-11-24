"""Eigene weg.li-Anzeigen zu E-Rollern (TBNR 101133) samt verkleinerter Totale.

Liest den API-Schlüssel aus WEG_LI_API_KEY, holt alle eigenen Anzeigen
seitenweise (wie die Wegli-Melder-App: GET /api/notices?page=N&per_page=100,
Header X-API-KEY) und schreibt nach --out:

  roller-meta.json   {"stand": ..., "items": [...]}
  roller-fotos.zip   flach, <anzeige-id>.jpg, max. 480 x 640 px, ohne EXIF

Totale = das erste Foto der Anzeige (wie in der App: der Roller-Weg lädt die
Gesamtansicht als Pflichtfoto zuerst hoch, Name roller_<zeit>_1.jpg). Trägt
das erste Foto nicht diesen Namen, kam die Anzeige auf anderem Weg zustande
und es ist nicht sicher die Totale - dann photo_kind "fallback".

Inkrementell: Fotos aus --alt-zip werden je Anzeige-ID wiederverwendet.
Jeder Fehler beim Abruf beendet das Skript mit Exit-Code 1, bevor etwas
geschrieben wird; der Workflow lässt das Release dann unangetastet.
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps

HOST = "https://www.weg.li"
TBNR = "101133"
BREITE = 480
HOEHE = 640   # Hochkant 9:16 wird sonst 853 px hoch und sprengt 40 KB
QUALITAET = 70
ZIEL_BYTES = 40 * 1024
BERLIN = ZoneInfo("Europe/Berlin")
TOTALE = re.compile(r"^roller_\d{8}_\d{6}_1\.jpe?g$", re.I)


def hole(url, key=None, versuche=3):
    kopf = {"Accept": "application/json", "User-Agent": "wegli-export-roller"}
    if key:
        kopf["X-API-KEY"] = key
    for n in range(versuche):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=90) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            # 4xx außer 429 ist endgültig (falscher Schlüssel usw.)
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code != 429:
                raise
            if n == versuche - 1:
                raise
            time.sleep(5 * (n + 1))


def alle_anzeigen(key):
    alle, vor_erste = [], None
    for seite in range(1, 401):
        t = hole(f"{HOST}/api/notices?page={seite}&per_page=100", key).decode("utf-8").strip()
        teil = json.loads(t)
        if isinstance(teil, dict):
            if teil.get("error") or teil.get("errors"):
                raise RuntimeError(f"weg.li meldet einen Fehler auf Seite {seite}")
            teil = teil.get("notices") or []
        if not teil:
            break
        erste = teil[0].get("token")
        if seite > 1 and erste is not None and erste == vor_erste:
            break
        vor_erste = erste
        alle.extend(teil)
    else:
        raise RuntimeError("mehr als 400 Seiten - Abbruch")
    return alle


def leer(v):
    return v is None or (isinstance(v, str) and v.strip() in ("", "null"))


def foto_url(f):
    if isinstance(f, str):
        return f
    u = f.get("url") or ""
    return u if u.startswith("http") else (HOST + u if u else "")


def foto_name(f):
    if isinstance(f, dict):
        return f.get("filename") or f.get("name") or (f.get("blob") or {}).get("filename") or ""
    return ""


def verkleinere(roh):
    with Image.open(io.BytesIO(roh)) as bild:
        bild = ImageOps.exif_transpose(bild).convert("RGB")
        f = min(BREITE / bild.width, HOEHE / bild.height, 1.0)
        if f < 1.0:
            bild = bild.resize((round(bild.width * f), round(bild.height * f)), Image.LANCZOS)
        q = QUALITAET
        while True:
            out = io.BytesIO()
            # ohne exif=..., also ohne EXIF/GPS
            bild.save(out, "JPEG", quality=q, optimize=True, progressive=True)
            if out.tell() <= ZIEL_BYTES or q <= 40:
                return out.getvalue()
            q -= 10


def passt(jpg):
    with Image.open(io.BytesIO(jpg)) as b:
        return b.width <= BREITE and b.height <= HOEHE


def lokalzeit(iso):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(BERLIN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--alt-zip")
    ap.add_argument("--alt-meta")
    a = ap.parse_args()

    key = os.environ.get("WEG_LI_API_KEY", "")
    if not key:
        sys.exit("WEG_LI_API_KEY fehlt")

    anzeigen = alle_anzeigen(key)
    if not anzeigen:
        sys.exit("weg.li lieferte keine einzige Anzeige - Abbruch")
    roller = [n for n in anzeigen
              if str(n.get("tbnr") or "").strip() == TBNR
              and str(n.get("status") or "").lower() not in ("deleted", "geloescht", "gelöscht")]
    print(f"{len(anzeigen)} eigene Anzeigen, davon {len(roller)} mit TBNR {TBNR}")

    # Schutz gegen halbe Antworten: deutlich weniger als beim letzten Mal -> rot
    if a.alt_meta and os.path.exists(a.alt_meta):
        vorher = len(json.load(open(a.alt_meta, encoding="utf-8")).get("items", []))
        if vorher and len(roller) < vorher * 0.5:
            sys.exit(f"nur {len(roller)} statt bisher {vorher} Roller-Anzeigen - Abbruch")

    alt = {}
    if a.alt_zip and os.path.exists(a.alt_zip):
        with zipfile.ZipFile(a.alt_zip) as z:
            alt = {n: z.read(n) for n in z.namelist() if n.lower().endswith(".jpg")}

    def eintrag(n):
        nid = str(n.get("token") or n.get("id"))
        fotos = [f for f in (n.get("photos") or []) if foto_url(f)]
        bild, art = None, None
        if fotos:
            art = "totale" if TOTALE.match(foto_name(fotos[0])) else "fallback"
            bild = alt.get(f"{nid}.jpg")
            if bild is not None and not passt(bild):
                bild = None   # aus einem Lauf mit anderen Grenzen - neu laden
            if bild is None:
                bild = verkleinere(hole(foto_url(fotos[0])))
        lz = lokalzeit(n["start_date"])
        lat, lng = n.get("latitude"), n.get("longitude")
        return {
            "id": nid,
            "date": lz.strftime("%Y-%m-%d"),
            "time": lz.strftime("%H:%M"),
            "street": None if leer(n.get("street")) else n["street"],
            "zip": None if leer(n.get("zip")) else str(n["zip"]),
            "lat": None if leer(lat) else float(lat),
            "lng": None if leer(lng) else float(lng),
            "tbnr": TBNR,
            "photo": f"{nid}.jpg" if bild else None,
            "photo_kind": art,
            "plate": None if leer(n.get("registration")) else n["registration"],
        }, bild

    with ThreadPoolExecutor(6) as pool:
        ergebnisse = list(pool.map(eintrag, roller))

    items = sorted((e for e, _ in ergebnisse), key=lambda e: (e["date"], e["time"], e["id"]), reverse=True)
    neu = sum(1 for (e, b) in ergebnisse if b is not None and f"{e['id']}.jpg" not in alt)

    os.makedirs(a.out, exist_ok=True)
    with zipfile.ZipFile(os.path.join(a.out, "roller-fotos.zip"), "w", zipfile.ZIP_STORED) as z:
        for e, b in sorted(ergebnisse, key=lambda x: x[0]["id"]):
            if b is not None:
                z.writestr(f"{e['id']}.jpg", b)
    stand = datetime.now(BERLIN).strftime("%Y-%m-%d")
    with open(os.path.join(a.out, "roller-meta.json"), "w", encoding="utf-8") as f:
        json.dump({"stand": stand, "items": items}, f, ensure_ascii=False, indent=1)

    groessen = [len(b) for _, b in ergebnisse if b is not None]
    print(f"{len(items)} Einträge, {len(groessen)} Fotos ({neu} neu geladen, "
          f"{len(groessen) - neu} aus dem letzten Release), "
          f"totale={sum(e['photo_kind'] == 'totale' for e in items)}, "
          f"fallback={sum(e['photo_kind'] == 'fallback' for e in items)}, "
          f"ohne Foto={sum(e['photo'] is None for e in items)}")
    if groessen:
        print(f"Fotogröße: max {max(groessen) // 1024} KB, Schnitt {sum(groessen) // len(groessen) // 1024} KB, "
              f"über 40 KB: {sum(g > ZIEL_BYTES for g in groessen)}")


if __name__ == "__main__":
    main()
