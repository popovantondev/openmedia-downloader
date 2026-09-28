# Privacy-safe screenshots

![Example app window in English](../assets/screenshots/en/main-window.png)

Public screenshots must come from an isolated demo setup:

1. Use a test build or a clean app profile with a synthetic queue. Do not sign in to a media account.
2. Use invented titles such as `Synthetic Demo Clip` and `Playlist Sample 01`, plus neutral example domains. Do not show real video links, history titles, destination folders, or account avatars.
3. Make sure no cookie, authentication, overwrite, or private error dialog is open.
4. Review the image and its file metadata before saving. Remove EXIF, GPS, author, device-name, and comment metadata; check the filename too.
5. Save only sanitized PNG files. Do not publish a capture of the real desktop or Finder window.

If a screenshot cannot be safely anonymized, recreate the scene. App icons are not UI screenshots and must not be presented as proof that the app was running. A screenshot used in a language guide must show the app UI in that same language; do not translate labels by drawing text over a capture from another locale. Store approved captures under `assets/screenshots/en/`, `assets/screenshots/de/`, or `assets/screenshots/ru/` according to the UI language.
