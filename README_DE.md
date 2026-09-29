# OpenMedia Downloader — deutsche Anleitung

[Benutzerhandbuch](https://popovantondev.github.io/openmedia-downloader/Guide-de.html)

OpenMedia Downloader ist eine native App für macOS 15 oder neuer auf Apple silicon. Sie untersucht unterstützte YouTube- und Vimeo-Links, lässt Medien und Qualität wählen und lädt Dateien oder nimmt unterstützte laufende Streams auf. Die Dokumentation beschreibt die Entwicklungslinie 5.5.0; die Paketierung ist noch nicht zur Weitergabe freigegeben ([Status](docs/RIGHTS_DE.md)).

**Ein DMG ist nicht enthalten:** Die Lizenz- und Herkunftsprüfung der in der App gebündelten Drittanbieter-Komponenten ist noch nicht abgeschlossen. Daher ist die Freigabe zur Weitergabe dieser Binärdatei nicht belegt. Das ist eine offene Lizenz-/Compliance-Prüfung und kein Fehler beim Erstellen der App. Für den Projektcode gilt zusätzlich PolyForm Strict: Die Lizenz erlaubt nichtkommerzielle Nutzung, gibt Empfängern aber kein Recht zur Weitergabe oder zur Erstellung abgeleiteter Werke. Siehe [Rechte und Paketstatus](docs/RIGHTS_DE.md).

![Hauptfenster von OpenMedia Downloader auf Deutsch](assets/screenshots/de/main-window.png)

## Download starten

1. Wählen Sie beim ersten Start Deutsch, Englisch oder Russisch. Die Wahl wird gespeichert und kann im Hauptfenster geändert werden. Standard ist das System-Erscheinungsbild; hell und dunkel sind ebenfalls wählbar.
2. Fügen Sie einen unterstützten Video- oder Playlist-Link ein. Titel und Status erscheinen schrittweise. Die Untersuchung startet keinen Download.
3. Wählen Sie bei einer Playlist die gewünschten Einträge aus. Anfangs ist kein Eintrag markiert.
4. Wählen Sie MP4-Video, AAC/M4A-Audio oder MP3-Audio sowie eine verfügbare Qualität und Übertragungsart. Das Angebot hängt von der Quelle ab.
5. Wählen Sie den Zielordner, fügen Sie Aufträge hinzu und starten Sie die Warteschlange. Aufträge lassen sich einzeln oder gemeinsam abbrechen.

Mehrere Formate eines Videos sind getrennte Aufträge. Standardmäßig laufen vier Dateien parallel; pro Datei sind vier Fragmente eingestellt. Beides lässt sich ändern. `≈` kennzeichnet eine Schätzung. Eine unbekannte Größe ist kein Wert von null.

## Formate und Streams

MP4-Video wird bei Bedarf zusammengeführt. AAC wird ohne erneute Kodierung kopiert und nur bei passender AAC-Quelle als M4A gespeichert. MP3 erfordert eine Audiokonvertierung. Details: [Formate und Streams](docs/FORMATS_AND_STREAMS.md).

Erkannte laufende Streams können ab dem aktuellen Zeitpunkt aufgenommen werden. Eine Aufnahme vom Anfang wird nur angeboten, wenn die Quelle diese Möglichkeit meldet; sie ist experimentell. Live-Fortschritt zeigt Zeit, Datenmenge und Rate statt eines erfundenen Prozents oder einer Endgröße. **Aufnahme beenden und speichern** beendet die Aufnahme. Erfolg wird erst nach Abschluss und Prüfung der Datei gemeldet.

## Cookies und Hilfe

Cookies sind optional und vertraulich. Öffentliche Videos können ohne Cookies versucht werden. Für Safari-Cookies benötigt **OpenMedia Downloader 5.5 selbst** den Festplattenvollzugriff. Safari braucht diese Freigabe nicht. Danach muss die App mit ⌘Q beendet und neu geöffnet werden. Ein Browser muss normalerweise nicht geöffnet bleiben, wenn seine Cookies gespeichert sind. Siehe [Cookie-Anleitung](docs/COOKIES.md).

Bei Fehlern prüfen Sie Link und Netzwerk, untersuchen Sie den Link erneut und versuchen Sie öffentliche Medien ohne Cookies. Fehlt ein Format, bietet es die Quelle eventuell nicht an. Weitere Schritte: [Fehlerbehebung](docs/TROUBLESHOOTING.md).

## Weitere Dokumente

- [Projektlizenz](LICENSE) — PolyForm Strict 1.0.0 für nichtkommerzielle Nutzung.
- [Architektur und Build](docs/ARCHITEKTUR_BUILD.md)
- [Änderungen](CHANGELOG.md)
- [Rechte- und Paketstatus](docs/RIGHTS_DE.md) · [Überblick zu Drittanbieter-Komponenten](docs/THIRD_PARTY_OVERVIEW_DE.md)
- [Datenschutzfreundliche Screenshot-Anleitung](docs/SCREENSHOTS.md)

Laden Sie nur Medien herunter, zu deren Speicherung Sie berechtigt sind. Die App umgeht weder DRM noch Bezahlschranken oder Kontorechte.
