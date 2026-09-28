# Rights and release status

**5.5.0 app distribution: not cleared.** No DMG is included because the license and source-provenance review for third-party components bundled in the app is incomplete. Redistribution clearance for that binary has therefore not been established. This is an open licensing/compliance review, not a technical packaging failure. This repository is for source and documentation review; it contains no app binary.

## Project code

The project code is covered by the [PolyForm Strict License 1.0.0](../LICENSE). It permits non-commercial use, including personal study and hobby use, but does not grant recipients downstream permission to distribute the project software or make changes or derivative works. The public repository is intended to let an employer review the project. GitHub's terms permit viewing and forking public repositories within its service; that platform permission is separate from the project license. See the [official GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service). This project-license restriction is separate from the open third-party clearance review for a binary built by the project owner.

This license applies only to project-owned material. Bundled third-party components remain under their own licenses.

## Bundled components

Bundled third-party components remain subject to their own licenses. Their original license texts are kept verbatim in `licenses/`; see the [third-party component overview](THIRD_PARTY_OVERVIEW_EN.md). Those component terms are separate from the project's source-code rights.

## Why distribution is blocked

The current M19 review has not closed the actual Deno dependency notice/linkage inventory, the native corresponding-source review for parts of yt-dlp, or the independent source-to-runtime provenance for CPython. A clean-checkout package build and remaining release acceptance are also required. A checksum, local signature, or successful test is not by itself redistribution clearance.

The 5.5 app is ad-hoc signed and not Apple-notarized. This document is a project status notice, not legal advice or a substitute for the license terms of bundled software.
