# Formate, Übertragung und Streams

![Hauptfenster auf Deutsch mit Format-, Qualitäts- und Übertragungsauswahl](../assets/screenshots/de/main-window.png)

## Datei-Downloads

| Auswahl | Ergebnis | Hinweise |
| --- | --- | --- |
| Video | MP4 | Video- und Audiospuren können getrennt vorliegen und werden bei Bedarf zusammengeführt. Die Quelle muss passende Formate anbieten. |
| AAC | M4A | Vorhandenes AAC wird ohne erneute Audiokodierung kopiert. Fehlt eine passende AAC-Quelle, wird kein AAC vorgetäuscht. |
| MP3 | MP3 | Audio wird mit FFmpeg umgewandelt. Die gewählte MP3-Bitrate ist eine Kodieroption, keine Zusage über die Qualität der Quelle. |

Qualitätsstufen hängen vom Video ab. Für AAC steht keine Videoauflösung zur Wahl. Die Übertragungsarten **Auto**, **Direkt** und **Fragmente** wählen unterschiedliche verfügbare Quellwege. Direkt kann scheitern, wenn die Quelle keinen passenden durchgehenden Stream anbietet. Fragmente können von HTTP-, HLS- oder DASH-Angeboten abhängen. Nicht jedes Video bietet alle Varianten.

Eine angezeigte Dateigröße kann geschätzt sein (`≈`); bei unbekannter Größe erscheint kein erfundener Nullwert. Video und Ton können für eine Schätzung getrennte Größen haben.

## Laufende Streams aufnehmen

Die App kann unterstützte geplante, laufende oder bereits beendete Übertragungen als solche markieren. Geplante Streams belegen keinen Downloadplatz. Bei einem laufenden Stream wählen Sie **Ab jetzt aufnehmen**. **Von Anfang an** wird nur angeboten, wenn die Quelle es ausdrücklich unterstützt; diese Funktion ist experimentell und kann dennoch an der Quelle scheitern.

Während einer Live-Aufnahme zeigt die App verstrichene Zeit, übertragene Daten und Rate. Eine Prozentzahl oder endgültige Dateigröße ist bei einer laufenden Sendung nicht bekannt. Mit **Stoppen und speichern** wird der Schreibvorgang sauber beendet. Die App meldet Erfolg erst, wenn Prozess, Ausgabe und Medienprüfung abgeschlossen sind. Bei Fehlern kann ein temporärer Wiederherstellungsort gemeldet werden; prüfen Sie den Fehlertext, bevor Sie Daten löschen.

AAC/M4A wird nur kopiert, wenn der Stream AAC enthält. MP3 wird nach dem Stoppen konvertiert. Nicht erkannte oder geschützte Streams werden nicht gewaltsam verarbeitet.
