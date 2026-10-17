"""Wandelt die WFS-Antwort (GeoJSON) der Münchner Stadtbezirke in stadtbezirke-muenchen.geojson um und prüft das Ergebnis.

Aufruf: python3 tools/stadtbezirke.py wfs.json stadtbezirke-muenchen.geojson
Ausgabe in WGS84 (lon/lat, 6 Nachkommastellen), je Feature nur die Properties nr und name.
Bezirke, die in der Quelle aus mehreren Teilflächen bestehen, werden zu einem MultiPolygon
zusammengefasst. Bricht mit Fehler ab, wenn die Prüfung nicht besteht.
"""
import json
import sys

from pyproj import Transformer

ANZAHL = 25
BREITE = (47.9, 48.4)
LAENGE = (11.2, 12.0)
WGS84 = ("EPSG::4326", "EPSG:4326", "CRS84")


def main(ein, aus):
    with open(ein, encoding="utf-8") as f:
        daten = json.load(f)
    crs = (daten.get("crs") or {}).get("properties", {}).get("name", "")
    print("Quellprojektion:", crs or "(keine Angabe, also WGS84)")
    if not crs or crs.endswith(WGS84):
        umrechnen = None
    else:
        # always_xy: Ausgabe lon/lat, egal wie EPSG:4326 die Achsen definiert
        umrechnen = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform

    def punkt(p):
        x, y = p[0], p[1]
        if umrechnen:
            x, y = umrechnen(x, y)
        return [round(x, 6), round(y, 6)]

    fehler = []
    bezirke = {}
    for feat in daten.get("features", []):
        props = feat.get("properties") or {}
        try:
            nr = int(props.get("sb_nummer"))
        except (TypeError, ValueError):
            fehler.append(f"ungültige sb_nummer {props.get('sb_nummer')!r}")
            continue
        name = (props.get("sb_name") or "").strip()
        g = feat.get("geometry") or {}
        if g.get("type") == "Polygon":
            polygone = [g["coordinates"]]
        elif g.get("type") == "MultiPolygon":
            polygone = g["coordinates"]
        else:
            fehler.append(f"Bezirk {nr}: Geometrie {g.get('type')!r}")
            continue
        polygone = [[[punkt(p) for p in ring] for ring in poly] for poly in polygone]
        b = bezirke.setdefault(nr, {"name": name, "polygone": []})
        if b["name"] != name:
            fehler.append(f"Bezirk {nr}: zwei Namen {b['name']!r} / {name!r}")
        b["polygone"].extend(polygone)

    print(f"{len(daten.get('features', []))} Features in der Quelle, {len(bezirke)} Bezirke")
    fehlend = sorted(set(range(1, ANZAHL + 1)) - set(bezirke))
    zuviel = sorted(set(bezirke) - set(range(1, ANZAHL + 1)))
    if fehlend:
        fehler.append(f"nr fehlt: {fehlend}")
    if zuviel:
        fehler.append(f"nr außerhalb 1–{ANZAHL}: {zuviel}")
    for nr, b in bezirke.items():
        if not b["name"]:
            fehler.append(f"Bezirk {nr} ohne Namen")
        for poly in b["polygone"]:
            for ring in poly:
                for lon, lat in ring:
                    if not (BREITE[0] <= lat <= BREITE[1] and LAENGE[0] <= lon <= LAENGE[1]):
                        fehler.append(f"Bezirk {nr}: Koordinate außerhalb des Rahmens ({lon}, {lat})")
                        break

    features = []
    for nr in sorted(bezirke):
        b = bezirke[nr]
        if len(b["polygone"]) == 1:
            geom = {"type": "Polygon", "coordinates": b["polygone"][0]}
        else:
            geom = {"type": "MultiPolygon", "coordinates": b["polygone"]}
        features.append({"type": "Feature", "properties": {"nr": nr, "name": b["name"]}, "geometry": geom})

    # Prüfung auf dem fertigen Ergebnis: genau 25 Features, jede nr genau einmal
    nrs = [f["properties"]["nr"] for f in features]
    if len(features) != ANZAHL:
        fehler.append(f"{len(features)} Features statt {ANZAHL}")
    if len(nrs) != len(set(nrs)):
        fehler.append("nr doppelt")

    for f in features:
        teile = len(f["geometry"]["coordinates"]) if f["geometry"]["type"] == "MultiPolygon" else 1
        print(f"{f['properties']['nr']:2d} – {f['properties']['name']}"
              + (f" ({teile} Teilflächen)" if teile > 1 else ""))
    if fehler:
        sys.exit("Prüfung fehlgeschlagen: " + "; ".join(fehler))

    # Ein Feature je Zeile: kompakt, aber Monatsstände bleiben vergleichbar
    with open(aus, "w", encoding="utf-8", newline="\n") as f:
        f.write('{"type":"FeatureCollection","features":[\n')
        f.write(",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in features))
        f.write("\n]}\n")
    print("Prüfung bestanden")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
