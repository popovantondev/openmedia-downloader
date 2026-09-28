# Architektur und Quellcode-Arbeit — einfach erklärt

![OpenMedia Downloader im deutschen Sprachmodus](../assets/screenshots/de/main-window.png)

## Aufbau

```text
SwiftUI/AppKit-Fenster
        ↓ Aktionen und Status
Swift OpenMediaCore (Modelle, Warteschlange, Prozesse)
        ↓ Argumente und JSON-Ereignisse
Python-Backend pro Auftrag
        ↓
yt-dlp · FFmpeg · Deno · Medienquelle
```

Swift zeigt Fenster, Dialoge und Status an. `OpenMediaCore` hält die Aufträge, begrenzt die gleichzeitigen Downloads und startet je Auftrag einen Backend-Prozess. Das Python-Backend untersucht Links, wählt Medienformate und lädt oder verarbeitet Daten. yt-dlp spricht mit unterstützten Anbietern; FFmpeg verarbeitet Medien; Deno stellt JavaScript-Funktionen bereit, die yt-dlp bei manchen Quellen braucht.

Die Bereiche kommunizieren über strukturierte Ereignisse. Dadurch kann das Fenster Titel und Playlist-Einträge schrittweise anzeigen und Tests können Backend-Prozesse kontrolliert ersetzen. Ein Stream hat einen eigenen Lebenszyklus; er wird nicht wie ein Download mit erfundener Endgröße behandelt.

## Voraussetzungen für die Entwicklung

- Mac mit Apple silicon und macOS 15 oder neuer
- Xcode oder Command Line Tools mit Swift 6 und macOS SDK
- Python 3 für Backend-Arbeit; die getestete Version und Pakete müssen zur jeweiligen Änderung passen
- Für lokale Medien-Integrationstests: die benötigten Werkzeuge FFmpeg/ffprobe und yt-dlp

Das öffentliche Quellpaket enthält absichtlich keine vorgebauten Medienprogramme, Python-Laufzeit oder vollständigen Drittanbieter-Quellarchive. Deshalb lässt sich daraus derzeit kein vollständiges App-Paket reproduzierbar bauen. Die Prüfung der Komponentenlizenzen und ihrer Herkunft ist noch offen; siehe [Rechte und Paketstatus](RIGHTS_DE.md) und den [Drittanbieter-Überblick](THIRD_PARTY_OVERVIEW_DE.md).

## Swift-Entwicklung

Im Projektordner kann SwiftPM die Swift-Komponenten bauen oder testen:

```sh
swift test
swift build
```

Das baut oder testet nur die Swift-Paketkomponenten. Es baut keine vollständige macOS-App und führt keine echten Medien-Downloads aus. Das öffentliche Paket enthält keinen freigegebenen Backend-Runtime-Build. Netzwerkprüfungen sind separate manuelle Tests und benötigen geeignete Testmedien und Werkzeuge.

## Paketstatus

Dies ist ein Quellcode- und Dokumentationspaket zur Projektprüfung, kein veröffentlichungsfertiger Build. Es enthält weder DMG noch App-Binärdateien. Eine vollständige Prüfung der Drittanbieter-Lizenzen und der Herkunft der enthaltenen Runtime-Komponenten steht noch aus. Deshalb geben die Build-Skripte in diesem Repository keine Freigabe zur Weitergabe. Siehe [Rechte und Paketstatus](RIGHTS_DE.md).
