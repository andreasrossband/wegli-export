# wegli-export

Wöchentliche Kopie des öffentlichen Datenexports von [weg.li](https://www.weg.li)
(`notices-csv-TT-MM-JJJJ-HH-MM.zip`, Spalten
`start_date,end_date,tbnr,street,city,zip,latitude,longitude`).

- Ein GitHub-Actions-Workflow (`.github/workflows/export.yml`) holt jeden Montag
  um 02:30 UTC den neuesten Export, prüft die ZIP-Datei und legt ihn unverändert
  als Release ab. Der Tag ist das Exportdatum (`JJJJ-MM-TT`).
- Es werden nur die letzten 8 Releases behalten.

Neueste Datei ohne Zugangsdaten abrufen:

```bash
curl -s https://api.github.com/repos/andreasrossband/wegli-export/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["assets"][0]["browser_download_url"])'
```

Die Daten stammen von weg.li; der API-Schlüssel liegt nur als Repository-Secret vor.
