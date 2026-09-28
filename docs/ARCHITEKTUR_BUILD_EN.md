# Architecture and source development — plain-language guide

![OpenMedia Downloader in English](../assets/screenshots/en/main-window.png)

## How the app is structured

```text
SwiftUI/AppKit window
        ↓ actions and status
Swift OpenMediaCore (models, queue, processes)
        ↓ arguments and JSON events
Python backend process per job
        ↓
yt-dlp · FFmpeg · Deno · media source
```

Swift displays windows, dialogs, and status. `OpenMediaCore` manages jobs, limits concurrent downloads, and starts a backend process for each job. The Python backend inspects links, selects media formats, and downloads or processes data. yt-dlp communicates with supported providers; FFmpeg handles media; Deno supplies JavaScript features that yt-dlp may need for some sources.

The parts communicate through structured events. This lets the window show titles and playlist items as they arrive and allows tests to replace backend processes in a controlled way. A stream has its own lifecycle; the app does not treat it like a download with a made-up final size.

## Development requirements

- Apple silicon Mac running macOS 15 or later.
- Xcode or Command Line Tools with Swift 6 and a macOS SDK.
- Python 3 and the packages needed for backend development and tests.
- FFmpeg/ffprobe and yt-dlp for local media integration checks.

This public source package intentionally omits prebuilt media tools, the Python runtime, and complete third-party source archives. It therefore cannot currently produce a reproducible full app package. Review of component licences and provenance remains open; see [rights and release status](RIGHTS_EN.md) and the [third-party component overview](THIRD_PARTY_OVERVIEW_EN.md).

## Swift development

In the project directory, Swift Package Manager can build or test the Swift components:

```sh
swift test
swift build
```

These commands build or test only the Swift package components. They do not create a full macOS app or perform real media downloads. This public package does not contain a cleared backend runtime build. Network checks are separate manual tests and require suitable test media and tools.

## Package status

This is a source-and-documentation package for project review, not a release-ready build. It contains no DMG or app binaries. A complete review of third-party licences and the provenance of bundled runtime components remains open. Build scripts in this repository do not grant redistribution clearance. See [rights and release status](RIGHTS_EN.md).
