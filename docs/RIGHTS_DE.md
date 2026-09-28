# OpenMedia Downloader 5.5.0 — Rechte- und Paketstatus

**Die Weitergabe der App 5.5.0 ist noch nicht freigegeben.** Ein DMG ist nicht enthalten, weil die Lizenz- und Herkunftsprüfung der in der App gebündelten Drittanbieter-Komponenten noch offen ist. Eine Freigabe zur Weitergabe dieser Binärdatei ist daher nicht belegt. Das ist eine offene Lizenz-/Compliance-Prüfung und kein technischer Build-Fehler. Dieses Repository dient der Einsicht in Quellcode und Dokumentation; es enthält keine App-Binärdatei.

## Projektcode

Für den Projektcode gilt die [PolyForm Strict License 1.0.0](../LICENSE). Sie erlaubt eine nichtkommerzielle Nutzung, zum Beispiel für persönliches Lernen und Hobbyprojekte. Sie gibt Empfängern jedoch kein nachgelagertes Recht, die Projektsoftware weiterzugeben oder Änderungen und abgeleitete Werke zu erstellen. Das öffentliche Repository soll einem möglichen Arbeitgeber die Prüfung des Projekts ermöglichen. GitHub erlaubt nach seinen eigenen Bedingungen das Ansehen und Forken öffentlicher Repositories innerhalb des Dienstes; diese Plattformberechtigung ist von der Projektlizenz getrennt. Siehe die [offiziellen GitHub-Nutzungsbedingungen](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service). Diese Beschränkung der Projektlizenz ist von der offenen Drittanbieterprüfung für ein vom Projektinhaber erstelltes App-Paket getrennt.

Diese Lizenz gilt nur für eigene Projektbestandteile. Für enthaltene Drittanbieter-Komponenten gelten weiterhin deren eigene Lizenzen. Die Projektlizenz und die noch offene Prüfung der Drittanbieter-Binärdateien sind getrennte Fragen.

## Enthaltene Komponenten

Für eingebundene Komponenten gelten deren eigene Lizenzen. Die Originaltexte sind unverändert in `licenses/` gespeichert. Siehe [Überblick zu Drittanbieter-Komponenten](THIRD_PARTY_OVERVIEW_DE.md). Diese Bedingungen ersetzen nicht die Regeln für den Projektcode.

## Gründe für die Sperre

Die M19-Prüfung hat den tatsächlichen Deno-Linkage- und Hinweisumfang noch nicht abgeschlossen. Offen sind außerdem Quellnachweise für native Teile von yt-dlp und ein unabhängiger Nachweis, dass der eingebundene CPython-Laufzeitcode aus den dokumentierten Quellen stammt. Ein sauberer Build aus einem frischen Checkout und weitere Abnahmetests fehlen ebenfalls. Prüfsumme, lokale Signatur oder erfolgreicher Test allein bedeuten keine Freigabe zur Weitergabe.

Die App 5.5 ist ad-hoc-signiert und nicht von Apple notarisiert. Dieses Dokument informiert über den Projektstatus und ist keine Rechtsberatung oder ein Ersatz für die Lizenzen der enthaltenen Software.
