# Troubleshooting

![Main window of the English app version](../assets/screenshots/en/main-window.png)

## A link stays in “Checking” or has no title

Check that the link is a supported video, playlist, or standard embed and that the Mac can reach the source. Select **Check links** again. A failed inspection does not start a download. A playlist may contain unavailable entries; other results can still be selected.

## The format or quality is missing

The app can show only formats offered by the source. AAC/M4A appears only when a suitable AAC audio stream exists. MP3 requires conversion. Direct transfer may be unavailable if there is no suitable continuous stream. Try Auto or Fragments if offered.

## Sign-in, cookies, or Safari fails

Cookies are optional. For public media, try **Continue without cookies**. Safari requires Full Disk Access for OpenMedia Downloader 5.5 itself, followed by restarting the app. See the [cookie guide](COOKIES_EN.md). Chrome and other browsers may show a Keychain prompt. A successful cookie-read check does not prove that the account can access a video.

## A stream will not start or save

A scheduled broadcast has not started yet. A completed broadcast can be checked again, but the source may not provide a playable recording yet. **From the beginning** is experimental and appears only when the source reports support. A finalization error is not reported as success. Follow any recovery-path instructions shown by the app.

## A download fails or is cancelled

Check the network and free disk space. A provider may have changed a URL, format, or sign-in requirement. Check the link again; for public links, try without cookies. Cancelling one job stops only that job; **Cancel all** stops the queue.

## Report a problem

Use an [issue template](../.github/ISSUE_TEMPLATE/). Describe the steps and expected result. Remove account names, personal paths, cookies, tokens, signed URLs, and private media titles from text, screenshots, and attachments. Do not attach a browser database or complete private logs.
