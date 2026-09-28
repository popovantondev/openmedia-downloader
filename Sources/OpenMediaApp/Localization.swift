import AppKit
import Foundation
import SwiftUI

enum InterfaceLanguage: String, CaseIterable, Identifiable {
    case russian = "ru"
    case german = "de"
    case english = "en"

    var id: String { rawValue }
    var name: String {
        switch self {
        case .russian: "Русский"
        case .german: "Deutsch"
        case .english: "English"
        }
    }
}

enum InterfaceAppearance: String, CaseIterable, Identifiable {
    case system, light, dark
    var id: String { rawValue }
    var colorScheme: ColorScheme? {
        switch self { case .system: nil; case .light: .light; case .dark: .dark }
    }
}

enum EditCommand: CaseIterable {
    case undo, redo, cut, copy, paste, selectAll
    var keyEquivalent: String {
        switch self { case .undo, .redo: "z"; case .cut: "x"; case .copy: "c"; case .paste: "v"; case .selectAll: "a" }
    }
    var modifiers: NSEvent.ModifierFlags {
        switch self { case .redo: [.command, .shift]; default: .command }
    }
}

enum CopyKey: String {
    case subtitle, links, linksHint, inspect, file, format, quality, mode, size, progress
    case download, cancelAll, close, closeTitle, closeMessage, keepOpen, stopAndSave
    case allFormats, allQuality, applyAll, parallelFiles, fragments, folder, chooseFolder
    case active, queued, completed, queueSize, unknown, log, clearFinished, addVariant, cancelTask
    case video, aac, mp3, best, automatic, direct, chunks
    case stageQueued, stageInspecting, stageScheduled, stageLive, stageEndedProcessing, stageFinalizing
    case stagePreparing, stageDownloading, stageMerging
    case stageOverwrite, stageCompleted, stageSkipped, stageCancelled, stageFailed, stageAuthentication
    case emptyQueue, waiting, unknownSize, estimatesHint, perSecond, remaining
    case authorization, authTitle, authExplanation, authPublic, authBrowser, authFile
    case browser, chooseCookies, noCookiesFile, checkCookies, authReadable, authSafari, authKeychain, authBrowserClosed
    case continuePublic, continueDownload, authPreparing, authError, authPrivacy, authDomainConsent, authDomainTitle, cancel, done
    case playlist, playlistHint, selectAll, selectNone, addSelected, skipPlaylist, available, unavailable
    case authRequired, availabilityUnknown, overwriteTitle, overwriteMessage, replace, skip
    case completionTitle, completionMessage, failed, skipped, cancelled, authNeededSummary, dismiss
    case startHint, duplicateNotice, openFolder, checking, authOnce, logEmpty, mediaVariants
    case about, quit, edit, undo, redo, cut, copy, paste, selectAllText, playlistReady
    case chooseLanguageTitle, chooseLanguageMessage, language, appearance, systemAppearance, lightAppearance, darkAppearance
    case retry, retryHint
    case authAccessDenied, authInvalidFile, authTimedOut, authCheckFailed
    case backendOutputInterrupted
    case streamNow, streamFromStart, fromStartUnavailable
    case closeFailedTitle, closeFailedMessage, continueWaiting, closeAnyway, recoveryFolder
    case cookiesFallbackWithoutAuthentication
    case publicAccessFallback
}

struct AppCopy {
    let language: InterfaceLanguage

    subscript(_ key: CopyKey) -> String {
        let values = Self.strings[key] ?? [key.rawValue, key.rawValue, key.rawValue]
        switch language {
        case .russian: return values[0]
        case .german: return values[1]
        case .english: return values[2]
        }
    }

    private static let strings: [CopyKey: [String]] = [
        .subtitle: ["Видео и аудио. В одном месте.", "Video und Audio. An einem Ort.", "Video and audio. In one place."],
        .links: ["Ссылки", "Links", "Links"],
        .linksHint: ["Вставьте ссылки на видео или плейлисты — по одной на строку. Проверка начнётся автоматически.", "Video- oder Playlist-Links einfügen — ein Link pro Zeile. Die Prüfung startet automatisch.", "Paste video or playlist links — one per line. Checking starts automatically."],
        .inspect: ["Проверить ссылки", "Links prüfen", "Check links"],
        .file: ["Файл / название", "Datei / Titel", "File / title"],
        .format: ["Формат", "Format", "Format"],
        .quality: ["Качество", "Qualität", "Quality"],
        .mode: ["Режим", "Modus", "Mode"],
        .size: ["Размер", "Größe", "Size"],
        .progress: ["Прогресс / статус", "Fortschritt / Status", "Progress / status"],
        .download: ["Начать скачивание", "Downloads starten", "Start downloads"],
        .cancelAll: ["Отменить всё", "Alle abbrechen", "Cancel all"],
        .stopAndSave: ["Остановить и сохранить", "Stoppen und speichern", "Stop and save"],
        .close: ["Закрыть", "Schließen", "Close"],
        .closeTitle: ["Закрыть программу?", "Programm schließen?", "Close the app?"],
        .closeMessage: ["Текущие загрузки и проверки будут отменены. Готовые файлы останутся на диске.", "Laufende Downloads und Prüfungen werden abgebrochen. Fertige Dateien bleiben erhalten.", "Active downloads and checks will be cancelled. Completed files will be kept."],
        .keepOpen: ["Продолжить работу", "Weiterarbeiten", "Keep open"],
        .allFormats: ["Формат всем", "Format für alle", "Format for all"],
        .allQuality: ["Качество всем", "Qualität für alle", "Quality for all"],
        .applyAll: ["Применить всем", "Für alle anwenden", "Apply to all"],
        .parallelFiles: ["Файлов одновременно", "Dateien gleichzeitig", "Concurrent files"],
        .fragments: ["Кусочков на файл", "Fragmente pro Datei", "Fragments per file"],
        .folder: ["Папка…", "Ordner…", "Folder…"],
        .chooseFolder: ["Куда сохранить файлы", "Speicherordner wählen", "Choose download folder"],
        .active: ["Активно", "Aktiv", "Active"],
        .queued: ["В очереди", "Wartend", "Queued"],
        .completed: ["Готово", "Fertig", "Completed"],
        .queueSize: ["Объём очереди", "Größe der Warteschlange", "Queue size"],
        .unknown: ["неизвестно", "unbekannt", "unknown"],
        .log: ["Отчёт", "Protokoll", "Log"],
        .clearFinished: ["Убрать завершённые", "Fertige entfernen", "Clear finished"],
        .addVariant: ["Добавить другой формат или качество", "Weiteres Format oder andere Qualität hinzufügen", "Add another format or quality"],
        .cancelTask: ["Отменить или удалить задачу", "Aufgabe abbrechen oder entfernen", "Cancel or remove task"],
        .video: ["Видео MP4", "Video MP4", "Video MP4"],
        .aac: ["AAC / M4A", "AAC / M4A", "AAC / M4A"],
        .mp3: ["MP3", "MP3", "MP3"],
        .best: ["Максимум", "Beste", "Best"],
        .automatic: ["Авто", "Auto", "Auto"],
        .direct: ["Целиком", "Direkt", "Direct"],
        .chunks: ["Кусочками", "Fragmente", "Chunks"],
        .stageQueued: ["В очереди", "Wartend", "Queued"],
        .stageInspecting: ["Проверяется", "Wird geprüft", "Checking"],
        .stageScheduled: ["Трансляция ещё не началась", "Übertragung hat noch nicht begonnen", "Stream has not started"],
        .stageLive: ["Записывается", "Wird aufgenommen", "Recording"],
        .stageEndedProcessing: ["Запись готовится", "Aufzeichnung wird verarbeitet", "Recording is being processed"],
        .stageFinalizing: ["Сохранение записи", "Aufzeichnung wird gespeichert", "Finalizing recording"],
        .streamNow: ["С текущего момента", "Ab jetzt aufnehmen", "Record from now"],
        .streamFromStart: ["С начала", "Von Anfang an", "Record from the beginning"],
        .fromStartUnavailable: ["Запись с начала недоступна", "Aufnahme ab Anfang nicht verfügbar", "Recording from the beginning is unavailable"],
        .stagePreparing: ["Подготовка", "Vorbereitung", "Preparing"],
        .stageDownloading: ["Скачивается", "Download läuft", "Downloading"],
        .stageMerging: ["Объединение / обработка", "Zusammenfügen / Verarbeiten", "Merging / processing"],
        .stageOverwrite: ["Файл уже существует", "Datei vorhanden", "File already exists"],
        .stageCompleted: ["Завершено", "Abgeschlossen", "Completed"],
        .stageSkipped: ["Пропущено", "Übersprungen", "Skipped"],
        .stageCancelled: ["Отменено", "Abgebrochen", "Cancelled"],
        .stageFailed: ["Ошибка", "Fehler", "Failed"],
        .stageAuthentication: ["Нужен вход", "Anmeldung nötig", "Sign-in required"],
        .emptyQueue: ["Здесь появятся названия видео", "Hier erscheinen die Videotitel", "Video titles will appear here"],
        .waiting: ["Готово к работе", "Bereit", "Ready"],
        .unknownSize: ["Размер пока неизвестен", "Größe noch unbekannt", "Size not yet known"],
        .estimatesHint: ["≈ — примерный размер. Размер потока оценивается по длительности и битрейту; он может измениться.", "≈ bedeutet geschätzt. Bei Streams hängt die Größe von Dauer und Bitrate ab und kann sich ändern.", "≈ means estimated. Stream sizes depend on duration and bitrate and may change."],
        .perSecond: ["/с", "/s", "/s"],
        .remaining: ["осталось", "übrig", "remaining"],
        .authorization: ["Авторизация…", "Anmeldung…", "Authorization…"],
        .authTitle: ["Доступ перед скачиванием", "Zugriff vor dem Download", "Access before downloading"],
        .authExplanation: ["Публичные видео обычно не требуют входа. Для закрытых или возрастных видео можно использовать вашу сессию браузера.", "Öffentliche Videos brauchen meist keine Anmeldung. Für private Videos oder Altersbeschränkungen können Sie Ihre Browser-Sitzung nutzen.", "Public videos usually need no sign-in. Private or age-restricted videos can use your browser session."],
        .authPublic: ["Только публичные видео", "Nur öffentliche Videos", "Public videos only"],
        .authBrowser: ["Cookies браузера", "Browser-Cookies", "Browser cookies"],
        .authFile: ["Файл cookies.txt", "Datei cookies.txt", "cookies.txt file"],
        .browser: ["Браузер", "Browser", "Browser"],
        .chooseCookies: ["Выбрать cookies.txt…", "cookies.txt wählen…", "Choose cookies.txt…"],
        .noCookiesFile: ["Файл не выбран", "Keine Datei gewählt", "No file selected"],
        .checkCookies: ["Подготовить cookies", "Cookies vorbereiten", "Prepare cookies"],
        .authReadable: ["Cookies доступны. Это не гарантирует вход или доступ к каждому видео.", "Cookies sind lesbar. Das garantiert keine Anmeldung und keinen Zugriff auf jedes Video.", "Cookies are readable. This does not guarantee sign-in or access to every video."],
        .authSafari: [
            "Для чтения cookies Safari разрешение нужно OpenMedia Downloader 5.5, а не самому Safari. Вход в YouTube этого разрешения не даёт.\n\n1. Откройте Системные настройки → Конфиденциальность и безопасность → Доступ к диску (Полный доступ к диску).\n2. Включите OpenMedia Downloader 5.5. Нет в списке? Добавьте текущую .app кнопкой «+».\n3. Закройте загрузчик (⌘Q), откройте заново и нажмите «Подготовить cookies».\n\nЭто широкий доступ к данным на Mac, не только к cookies. Для публичных видео можно продолжить без него и без cookies.",
            "Zum Lesen der Safari-Cookies braucht OpenMedia Downloader 5.5 die Erlaubnis, nicht Safari selbst. Die Anmeldung bei YouTube gibt diese Erlaubnis nicht.\n\n1. Öffnen Sie Systemeinstellungen → Datenschutz & Sicherheit → Festplattenvollzugriff.\n2. Aktivieren Sie OpenMedia Downloader 5.5. Fehlt der Eintrag? Fügen Sie die aktuelle .app mit „+“ hinzu.\n3. Beenden Sie den Downloader (⌘Q), öffnen Sie ihn neu und wählen Sie „Cookies vorbereiten“.\n\nDiese Erlaubnis gibt breiten Zugriff auf Mac-Daten, nicht nur auf Cookies. Öffentliche Videos können Sie ohne diese Erlaubnis und ohne Cookies laden.",
            "To read Safari cookies, OpenMedia Downloader 5.5 needs permission, not Safari itself. Signing in to YouTube does not grant this permission.\n\n1. Open System Settings → Privacy & Security → Full Disk Access.\n2. Enable OpenMedia Downloader 5.5. Not listed? Add the current .app using “+”.\n3. Quit the downloader (⌘Q), reopen it and choose “Prepare cookies”.\n\nThis grants broad access to Mac data, not just cookies. Public videos can be downloaded without this permission or cookies."
        ],
        .authBrowserClosed: [
            "Браузер обычно можно закрыть: читаются сохранённые cookies. Заранее войдите в аккаунт в обычном окне, не выходите из аккаунта. Если при закрытии cookies удаляются, оставьте браузер открытым до их подготовки.",
            "Der Browser muss meist nicht offen bleiben: Gespeicherte Cookies werden gelesen. Melden Sie sich vorher in einem normalen Fenster an und nicht wieder ab. Löscht der Browser Cookies beim Beenden, lassen Sie ihn bis zur Vorbereitung offen.",
            "The browser usually does not need to stay open: saved cookies are read. Sign in first in a normal window and do not sign out. If closing the browser deletes cookies, keep it open until preparation finishes."
        ],
        .authKeychain: ["macOS может отдельно запросить доступ к «Связке ключей» для расшифровки cookies браузера. Решение принимаете вы в системном окне; вводить пароль YouTube в программу не нужно.", "macOS kann für Browser-Cookies den Zugriff auf den Schlüsselbund anfragen. Sie entscheiden im Systemdialog. Ein YouTube-Passwort wird in der App nicht gebraucht.", "macOS may ask for Keychain access to decrypt browser cookies. You decide in the system dialog; the app does not need your YouTube password."],
        .continuePublic: ["Продолжить без cookies", "Ohne Cookies fortfahren", "Continue without cookies"],
        .continueDownload: ["Продолжить скачивание", "Downloads fortsetzen", "Continue downloads"],
        .authPreparing: ["Подготовка доступа…", "Zugriff wird vorbereitet…", "Preparing access…"],
        .authError: ["Не удалось подготовить cookies", "Cookies konnten nicht vorbereitet werden", "Could not prepare cookies"],
        .authPrivacy: ["Копия cookies хранится только на этом Mac и используется для запросов к видеосервисам и отдельно выбранным сайтам. После завершения сессии временная копия удаляется.", "Die Cookie-Kopie liegt nur auf diesem Mac und wird für Anfragen an Videodienste und ausdrücklich ausgewählte Websites genutzt. Sie wird nach der Sitzung gelöscht.", "The cookie copy is stored only on this Mac and used for video services and websites you explicitly select. It is removed when the session ends."],
        .authDomainTitle: ["Дополнительные сайты", "Zusätzliche Websites", "Additional websites"],
        .authDomainConsent: ["Это необязательное разрешение: cookies выбранных сайтов сохраняются во временной приватной сессии. Стандартные правила хоста определяют, какой сайт получит каждый cookie; посторонние сайты исключены.", "Diese Zustimmung ist freiwillig: Cookies der ausgewählten Websites werden in der privaten temporären Sitzung gespeichert. Die üblichen Host-Regeln bestimmen, welche Website jedes Cookie erhält; andere Websites sind ausgeschlossen.", "This optional consent retains cookies for selected sites in the private temporary session. Standard host rules decide which site receives each cookie; unrelated sites are excluded."],
        .cookiesFallbackWithoutAuthentication: ["Cookies недоступны — публичные ссылки проверяются и скачиваются без авторизации.", "Cookies nicht verfügbar – öffentliche Links werden ohne Anmeldung geprüft und geladen.", "Cookies unavailable — public links are checked and downloaded without signing in."],
        .publicAccessFallback: ["Сервер отклонил загрузку с cookies. Публичный доступ подтверждён — повторяю без входа.", "Der Server hat den Download mit Cookies abgelehnt. Öffentlicher Zugriff ist bestätigt – neuer Versuch ohne Anmeldung.", "The server rejected the download with cookies. Public access is confirmed — retrying without signing in."],
        .cancel: ["Отмена", "Abbrechen", "Cancel"],
        .done: ["Готово", "Fertig", "Done"],
        .playlist: ["Выберите видео из плейлиста", "Videos aus der Playlist wählen", "Choose playlist videos"],
        .playlistHint: ["Отметьте нужные видео. Кнопка + добавит ещё один формат или качество того же видео.", "Gewünschte Videos markieren. + fügt ein weiteres Format oder eine andere Qualität hinzu.", "Select the videos you want. + adds another format or quality of the same video."],
        .selectAll: ["Выбрать доступные", "Verfügbare auswählen", "Select available"],
        .selectNone: ["Снять выбор", "Auswahl aufheben", "Select none"],
        .addSelected: ["Добавить выбранные", "Auswahl hinzufügen", "Add selected"],
        .skipPlaylist: ["Пропустить плейлист", "Playlist überspringen", "Skip playlist"],
        .available: ["Доступно", "Verfügbar", "Available"],
        .unavailable: ["Недоступно", "Nicht verfügbar", "Unavailable"],
        .authRequired: ["Нужна авторизация", "Anmeldung erforderlich", "Authorization required"],
        .availabilityUnknown: ["Доступ уточнится при запуске", "Zugriff wird beim Start geprüft", "Access checked when starting"],
        .overwriteTitle: ["Заменить существующий файл?", "Vorhandene Datei ersetzen?", "Replace existing file?"],
        .overwriteMessage: ["В папке уже есть этот файл. Заменить его новой загрузкой?", "Diese Datei ist im Ordner vorhanden. Durch den neuen Download ersetzen?", "This file is already in the folder. Replace it with the new download?"],
        .replace: ["Заменить", "Ersetzen", "Replace"],
        .skip: ["Пропустить", "Überspringen", "Skip"],
        .completionTitle: ["Все загрузки завершены", "Alle Downloads beendet", "All downloads finished"],
        .completionMessage: ["Подробности и ошибки доступны в отчёте.", "Details und Fehler stehen im Protokoll.", "Details and errors are available in the log."],
        .failed: ["Ошибок", "Fehler", "Failed"],
        .skipped: ["Пропущено", "Übersprungen", "Skipped"],
        .cancelled: ["Отменено", "Abgebrochen", "Cancelled"],
        .authNeededSummary: ["Некоторым видео нужен вход. Откройте авторизацию и повторите только эти задачи.", "Einige Videos brauchen eine Anmeldung. Öffnen Sie die Anmeldung und starten Sie nur diese Aufgaben erneut.", "Some videos need sign-in. Open authorization and retry only those tasks."],
        .dismiss: ["Понятно", "Verstanden", "OK"],
        .startHint: ["Перед очередью можно один раз подготовить cookies или продолжить без входа.", "Vor der Warteschlange können Sie Cookies einmal vorbereiten oder ohne Anmeldung fortfahren.", "Before the batch, prepare cookies once or continue without sign-in."],
        .duplicateNotice: ["Одинаковые варианты не будут загружены дважды.", "Gleiche Varianten werden nicht doppelt geladen.", "Identical variants will not be downloaded twice."],
        .openFolder: ["Открыть папку", "Ordner öffnen", "Open folder"],
        .checking: ["Проверка ссылок…", "Links werden geprüft…", "Checking links…"],
        .authOnce: ["Одна подготовка для всей очереди", "Eine Vorbereitung für die Warteschlange", "One preparation for the whole batch"],
        .logEmpty: ["Здесь появится ход проверки и скачивания.", "Hier erscheinen Prüfung und Download-Fortschritt.", "Checks and download details will appear here."],
        .mediaVariants: ["Вариантов", "Varianten", "Variants"],
        .about: ["О программе OpenMedia Downloader", "Über OpenMedia Downloader", "About OpenMedia Downloader"],
        .quit: ["Завершить OpenMedia Downloader", "OpenMedia Downloader beenden", "Quit OpenMedia Downloader"],
        .edit: ["Интерфейс", "Oberfläche", "Interface"],
        .undo: ["Отменить действие", "Rückgängig", "Undo"],
        .redo: ["Повторить действие", "Wiederholen", "Redo"],
        .cut: ["Вырезать", "Ausschneiden", "Cut"],
        .copy: ["Копировать", "Kopieren", "Copy"],
        .paste: ["Вставить", "Einfügen", "Paste"],
        .selectAllText: ["Выделить всё", "Alles auswählen", "Select All"],
        .playlistReady: ["Плейлист готов к выбору", "Playlist bereit zur Auswahl", "Playlist ready for selection"],
        .retry: ["Повторить", "Erneut versuchen", "Retry"],
        .retryHint: ["Вернуть задачу в очередь. Затем нажмите «Начать скачивание».", "Aufgabe wieder vormerken. Danach auf „Downloads starten“ klicken.", "Return this task to the queue, then click Start downloads."],
        .authAccessDenied: ["Не удалось прочитать или расшифровать cookies браузера. Safari может требовать разрешение на чтение файлов, Chrome и Opera — доступ к «Связке ключей». Выберите другой браузер или cookies.txt. Публичные видео можно скачивать без cookies.", "Browser-Cookies konnten nicht gelesen oder entschlüsselt werden. Safari kann Dateizugriff brauchen, Chrome und Opera den Schlüsselbund. Wählen Sie einen anderen Browser oder cookies.txt. Öffentliche Videos gehen ohne Cookies.", "Browser cookies could not be read or decrypted. Safari may need file access; Chrome and Opera may need Keychain access. Choose another browser or cookies.txt. Public videos work without cookies."],
        .authInvalidFile: ["Не удалось прочитать файл cookies. Выберите корректный cookies.txt в формате Netscape.", "Die Cookie-Datei ist nicht lesbar oder ungültig. Wählen Sie eine gültige cookies.txt-Datei im Netscape-Format.", "The cookie file is unreadable or invalid. Choose a valid cookies.txt file in Netscape format."],
        .authTimedOut: ["Проверка авторизации заняла слишком много времени и остановлена. Повторите попытку или продолжите без cookies.", "Die Prüfung hat zu lange gedauert und wurde beendet. Versuchen Sie es erneut oder fahren Sie ohne Cookies fort.", "The authorization check took too long and was stopped. Try again or continue without cookies."],
        .authCheckFailed: ["Не удалось проверить cookies. Попробуйте другой браузер, импорт файла или продолжите без cookies.", "Cookies konnten nicht geprüft werden. Versuchen Sie einen anderen Browser, eine Cookie-Datei oder fahren Sie ohne Cookies fort.", "Cookies could not be checked. Try another browser, import a cookie file, or continue without cookies."],
        .backendOutputInterrupted: ["Не получено корректное завершение загрузки. Зависший процесс остановлен. Повторите попытку.", "Der Download wurde nicht korrekt beendet. Der blockierte Prozess wurde gestoppt. Versuchen Sie es erneut.", "The download did not finish cleanly. The stalled process was stopped. Try again."],
        .closeFailedTitle: ["Сохранение ещё выполняется", "Speichern läuft noch", "Saving is still in progress"],
        .closeFailedMessage: ["Некоторые процессы ещё завершаются. Можно подождать дальше или закрыть программу принудительно. Незавершённая запись останется в скрытой папке .omd-recording-* внутри выбранной папки сохранения и может потребовать восстановления.", "Einige Prozesse werden noch beendet. Sie können weiter warten oder das Programm erzwingen. Eine unvollständige Aufnahme bleibt im versteckten Ordner .omd-recording-* im gewählten Speicherordner und muss eventuell wiederhergestellt werden.", "Some processes are still stopping. You can keep waiting or force quit. An unfinished recording will remain in the hidden .omd-recording-* folder inside the selected destination and may need recovery."],
        .continueWaiting: ["Продолжить ожидание", "Weiter warten", "Keep waiting"],
        .closeAnyway: ["Закрыть принудительно", "Trotzdem schließen", "Force close"],
        .recoveryFolder: ["Папка, где останется незавершённая запись:", "Ordner mit der unvollständigen Aufnahme:", "Folder containing the unfinished recording:"],
        .chooseLanguageTitle: ["Выберите язык", "Sprache auswählen", "Choose a language"],
        .chooseLanguageMessage: ["Язык можно изменить в главном окне.", "Die Sprache kann im Hauptfenster geändert werden.", "You can change the language in the main window."],
        .language: ["Язык", "Sprache", "Language"],
        .appearance: ["Внешний вид", "Erscheinungsbild", "Appearance"],
        .systemAppearance: ["Системная", "System", "System"],
        .lightAppearance: ["Светлая", "Hell", "Light"],
        .darkAppearance: ["Тёмная", "Dunkel", "Dark"]
    ]
}
