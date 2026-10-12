"""Wandelt die Overpass-Antwort (JSON) in adressen-muenchen.csv um und prüft das Ergebnis.

Aufruf: python3 tools/adressen.py osm.json adressen-muenchen.csv
Bricht mit Fehler ab, wenn die Prüfung nicht besteht; die Ausgabedatei ist dann unbrauchbar.
"""
import csv
import json
import sys

MIN_ZEILEN = 100_000
BREITE = (47.9, 48.4)
LAENGE = (11.2, 12.0)


def main(ein, aus):
    with open(ein, encoding="utf-8") as f:
        daten = json.load(f)
    if daten.get("remark"):
        sys.exit(f"Overpass meldet: {daten['remark']}")
    print("OSM-Stand:", daten.get("osm3s", {}).get("timestamp_osm_base"))

    zeilen = []
    ohne_strasse = ohne_koord = 0
    for e in daten.get("elements", []):
        tags = e.get("tags", {})
        strasse = tags.get("addr:street", "").strip()
        if not strasse:
            ohne_strasse += 1
            continue
        if e["type"] == "node":
            lat, lon = e.get("lat"), e.get("lon")
        else:
            c = e.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            ohne_koord += 1
            continue
        zeilen.append((
            f"{lat:.6f}", f"{lon:.6f}", strasse,
            tags.get("addr:housenumber", ""),
            tags.get("addr:postcode", ""),
            tags.get("addr:city", ""),
        ))

    # Stabile Reihenfolge, damit sich Monatsstände sinnvoll vergleichen lassen
    zeilen.sort(key=lambda z: (z[4], z[2], z[3], z[0], z[1]))

    fehler = []
    if len(zeilen) < MIN_ZEILEN:
        fehler.append(f"nur {len(zeilen)} Zeilen (mindestens {MIN_ZEILEN})")
    ausserhalb = [z for z in zeilen
                  if not (BREITE[0] <= float(z[0]) <= BREITE[1]
                          and LAENGE[0] <= float(z[1]) <= LAENGE[1])]
    if ausserhalb:
        fehler.append(f"{len(ausserhalb)} Koordinaten außerhalb des Rahmens, z. B. {ausserhalb[0]}")

    print(f"{len(zeilen)} Adressen, {ohne_strasse} ohne addr:street weggelassen, "
          f"{ohne_koord} ohne Koordinate weggelassen")
    if fehler:
        sys.exit("Prüfung fehlgeschlagen: " + "; ".join(fehler))

    with open(aus, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["lat", "lon", "strasse", "hausnummer", "plz", "ort"])
        w.writerows(zeilen)
    print("Prüfung bestanden")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
