# OpenMedia Downloader — English guide

[User guide](https://popovantondev.github.io/openmedia-downloader/Guide-en.html)

OpenMedia Downloader is a native app for macOS 15 or later on Apple silicon. It inspects supported YouTube and Vimeo links, lets you choose media and quality, and downloads files or records supported ongoing streams. Public documentation describes the 5.5.0 development line; packaging is not cleared for distribution yet ([status](docs/RIGHTS_EN.md)).

**No DMG is included:** the licensing and source-provenance review for third-party components bundled in the app is not complete, so redistribution clearance for that binary has not been established. This is an open licensing/compliance gate, not a packaging error. The project code has a separate PolyForm Strict license; it permits non-commercial use but does not grant recipients downstream redistribution or derivative-work rights. See [rights and release status](docs/RIGHTS_EN.md).

![OpenMedia Downloader main window in English](assets/screenshots/en/main-window.png)

## Start a download

1. On first launch, choose English, German, or Russian. The choice is remembered; change it in the main window at any time. System appearance is the default; light and dark appearance can be selected.
2. Paste a supported video or playlist link. Inspection shows available titles and statuses as they arrive. Inspection does not enqueue a download.
3. For a playlist, select the items you want. Rows start unchecked; unavailable entries may remain in the list with a status.
4. Choose MP4 video, AAC/M4A audio, or MP3 audio, then choose an available quality and transfer mode. Options depend on the source.
5. Choose an output folder, add the jobs, and start. The queue shows each job separately. You can cancel an item or cancel all jobs.

Several formats of one video are separate jobs. The default concurrency is four files and four fragments per file; these settings can be changed. A displayed `≈` marks an estimate. Unknown size is shown as unknown, not zero.

## Formats and streams

MP4 video is remuxed where needed. AAC is copied without re-encoding and saved in an M4A container only when a suitable AAC source exists. MP3 requires audio conversion. See [format, quality and transfer details](docs/FORMATS_AND_STREAMS_EN.md).

Supported live or ongoing streams are identified during inspection. Choose recording from the current point, or choose from the beginning only when the source reports that option as supported. Live progress uses elapsed time, bytes, and rate; it does not invent a percentage or final size. Use **Stop and save** to end a recording cleanly. A recording is complete only after finalization and validation. See the [formats and streams guide](docs/FORMATS_AND_STREAMS_EN.md) for limitations.

## Cookies and troubleshooting

Cookies are optional and sensitive. Public videos can be attempted without them. Safari cookie access requires Full Disk Access granted to **OpenMedia Downloader 5.5**, followed by quitting and reopening that app. Safari itself does not need this permission, and a browser normally does not have to remain open after its cookies have been saved. Details: [cookie guide](docs/COOKIES_EN.md).

If a link cannot be inspected, verify that it is supported and reachable, then inspect again. If a format is missing, the source may not provide it. For cookie errors, retry without cookies for public media or choose another supported authentication method. See [troubleshooting](docs/TROUBLESHOOTING_EN.md).

## More

- [Project license](LICENSE) — PolyForm Strict 1.0.0, for non-commercial use.
- [Architecture and build guide](docs/ARCHITEKTUR_BUILD_EN.md)
- [Changelog](CHANGELOG_EN.md)
- [Rights and release status](docs/RIGHTS_EN.md) · [Third-party component overview](docs/THIRD_PARTY_OVERVIEW_EN.md)
- [Privacy-safe screenshot guide](docs/SCREENSHOTS_EN.md)

Only download media you have permission to save. The app does not bypass DRM, paywalls, or account access controls.
