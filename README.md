# OpenMedia Downloader

<!-- public-release:start -->
Inspect supported media links and select authorized downloads or supported stream recordings.

**macOS 15+ · Apple Silicon · Source only 5.5.0**

**[Source](https://github.com/popovantondev/openmedia-downloader)** · **[User guide](https://popovantondev.github.io/openmedia-downloader/Guide-en.html)** · **[Report a problem](https://github.com/popovantondev/openmedia-downloader/issues/new/choose)**

**Requirements and limitations:** Source only: redistribution clearance for bundled third-party components is pending. Save only media you are authorized to keep.

**First steps:** Read the documentation and release status. No ready-to-use app DMG or ZIP is offered.
<!-- public-release:end -->

A native macOS app for inspecting supported YouTube and Vimeo links, choosing media, and downloading or recording streams. The interface is available in English, Deutsch, and Русский.

**Current documentation describes the 5.5.0 development line.** Release packaging is not yet cleared for distribution; see [rights and release status](docs/RIGHTS_EN.md). The app is intended for macOS 15 or later on Apple silicon. Use only media you are authorized to save. The app does not bypass DRM, account restrictions, or paid access.

**No DMG is included:** the licensing and source-provenance review for third-party components bundled in the app is not complete, so redistribution clearance for that binary has not been established. This is an open licensing/compliance gate, not a packaging error. The project code has a separate PolyForm Strict license; it permits non-commercial use but does not grant recipients downstream redistribution or derivative-work rights. See [rights and release status](docs/RIGHTS_EN.md).

![OpenMedia Downloader 5.5 main window in English](assets/screenshots/en/main-window.png)

## Guides

- [English guide](README_EN.md)
- [Русское руководство](README_RU.md)
- [Deutsche Anleitung](README_DE.md)

## Features

- Progressive title and playlist discovery; playlist items begin unselected.
- MP4 video, AAC audio saved as M4A when available, and MP3 audio conversion.
- Quality and automatic, direct, or segmented transfer choices where the source offers them.
- Multiple variants, a queue, per-file progress, cancellation, and concurrent downloads.
- Detection and recording of supported ongoing streams, with a clear stop-and-save action.
- Optional browser authentication. Public media can be tried without cookies.

Formats and transfer choices depend on the source. See [formats and streams](docs/FORMATS_AND_STREAMS_EN.md).

## First run and downloads

1. Open the app and choose Deutsch, English, or Русский. The choice is remembered and can be changed in the window.
2. Paste one or more supported links and inspect them. Select playlist items explicitly.
3. Choose format, quality, transfer mode, and destination; add the selected jobs to the queue.
4. Start the queue. Check each row's status; cancel an item or stop the queue when needed.

For Safari authentication, macOS requires Full Disk Access for **the OpenMedia Downloader 5.5 app itself**. Safari does not need this permission. The app must be quit and reopened after changing the permission. A browser with saved cookies normally does not need to stay open. See the [cookie guide](docs/COOKIES_EN.md) for limits and alternatives.

## Build from source

The [architecture and source-development guide](docs/ARCHITEKTUR_BUILD_EN.md) explains the app structure and Swift checks. This source-only snapshot omits bundled runtimes, media-tool binaries, and third-party source archives, so it is not a complete app build kit. No command publishes or uploads the project.

## Project records

- [Project license](LICENSE) — PolyForm Strict 1.0.0, for non-commercial use.
- [Changelog](CHANGELOG_EN.md)
- [Troubleshooting](docs/TROUBLESHOOTING_EN.md)
- [Rights and release status](docs/RIGHTS_EN.md)
- [Third-party component overview](docs/THIRD_PARTY_OVERVIEW_EN.md)
- [Screenshot guidance](docs/SCREENSHOTS_EN.md)

Bug reports should use the [issue forms](https://github.com/popovantondev/openmedia-downloader/issues/new/choose). Please do not attach browser profiles, cookies, account details, private logs, or unredacted screenshots.
