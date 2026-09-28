# Drittanbieter-Komponenten und Lizenzindex

Dieser Index erklärt die Drittanbieter-Lizenzdateien im Ordner [`licenses/`](../licenses/). Er ersetzt sie nicht: Originale Lizenz- und Copyright-Texte bleiben unverändert. Dass eine Datei hier aufgeführt ist, beweist nicht, dass der entsprechende Code in eine bestimmte App-Version gelinkt wurde.

**Die Weitergabe ist blockiert.** Deno-Hinweise und Linkage, native Quellen und Build-Provenienz sowie die Prüfung des endgültigen App-Pakets sind noch offen. Siehe [Rechte- und Paketstatus](RIGHTS_DE.md). Der ausführliche interne Prüfbericht gehört nicht zu den öffentlichen Dokumenten.

## Eigenständiges yt-dlp-Paket

Die gebündelte yt-dlp-Datei ist ein Upstream-PyInstaller-Build mit zusätzlichen Komponenten. Zugehörige Upstream-Texte und Hinweise:

- [yt-dlp-Quelllizenz](../licenses/yt-dlp-LICENSE), [Sammlung der Drittanbieter-Lizenzen](../licenses/yt-dlp-THIRD_PARTY_LICENSES.txt) und [GPL-Version 3](../licenses/GPL-3.0.txt).
- [PyInstaller-Hinweis 6.22.0](../licenses/yt-dlp-PyInstaller-6.22.0-COPYING.txt) und [Lizenz für typing_extensions 4.16.0](../licenses/yt-dlp-typing_extensions-4.16.0-LICENSE.txt).
- Der Hinweis für OpenSSL 3.5.7 im Paket verwendet denselben geprüften Text wie [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt); der Zstandard-Hinweis liegt im [zstd-Lizenztext von Python](../licenses/Python-3.14-zstd-LICENSE.txt).

## Native Quellen von curl-cffi

Diese Texte gehören zu Quellarchiven aus dem gepinnten Upstream-Buildrezept. Die genaue Übereinstimmung mit dem eingebetteten universal2-Binary einschließlich Patches und Compileroptionen ist nicht belegt.

- [curl-impersonate](../licenses/curl-impersonate-2.0.0-LICENSE.txt), [curl](../licenses/curl-8.21.0-COPYING.txt), [BoringSSL](../licenses/BoringSSL-156c7b75-LICENSE.txt) und [fiat](../licenses/BoringSSL-fiat-LICENSE.txt).
- [Brotli](../licenses/Brotli-1.2.0-LICENSE.txt), [nghttp2](../licenses/nghttp2-1.63.0-COPYING.txt), [nghttp3](../licenses/nghttp3-1.15.0-COPYING.txt) und [ngtcp2](../licenses/ngtcp2-1.20.0-COPYING.txt).
- [zlib](../licenses/zlib-1.3.1-LICENSE.txt) und [Zstandard](../licenses/Python-3.14-zstd-LICENSE.txt).

## FFmpeg und LAME

- [FFmpeg-LGPL-2.1-Text](../licenses/FFmpeg-8.1.2-LGPL-2.1.txt), [FFmpeg-Lizenz und Hinweise](../licenses/FFmpeg-8.1.2-LICENSE.md) und [LAME-COPYING](../licenses/LAME-3.100-COPYING.txt).

## Deno, RustyV8, V8 und Web-/Runtime-Typen

- Haupttexte: [Deno](../licenses/deno-LICENSE.md), [RustyV8](../licenses/Deno-RustyV8-150.4.0-LICENSE.txt), [V8](../licenses/Deno-V8-15.0.245.2-LICENSE.txt), [V8-Lizenz](../licenses/Deno-V8-15.0.245.2-LICENSE.v8.txt), [fdlibm](../licenses/Deno-V8-15.0.245.2-LICENSE.fdlibm.txt), [Strongtalk](../licenses/Deno-V8-15.0.245.2-LICENSE.strongtalk.txt), [Node-Typen](../licenses/Deno-2.9.6-Node-Types-LICENSE.txt), [Undici-Typen](../licenses/Deno-2.9.6-Undici-Types-LICENSE.txt) und [WebGPU](../licenses/Deno-2.9.6-WebGPU-LICENSE.md).
- Cargo-Pakettexte: [Inflector](../licenses/Deno-Cargo-Inflector-0.11.4-LICENSE.md), [aead](../licenses/Deno-Cargo-aead-0.5.2-LICENSE-MIT.txt), [aes-gcm](../licenses/Deno-Cargo-aes-gcm-0.10.3-LICENSE-MIT.txt), [alloc-stdlib](../licenses/Deno-Cargo-alloc-stdlib-0.2.2-LICENSE.txt), [aws-lc-rs](../licenses/Deno-Cargo-aws-lc-rs-1.16.3-LICENSE.txt), [aws-lc-sys](../licenses/Deno-Cargo-aws-lc-sys-0.40.0-LICENSE.txt), [backhand Apache](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-APACHE.txt), [backhand MIT](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-MIT.txt), [bytes-str](../licenses/Deno-Cargo-bytes-str-0.2.7-LICENSE-APACHE.txt), [cranelift-assembler-x64](../licenses/Deno-Cargo-cranelift-assembler-x64-0.117.2-LICENSE.txt), [dlopen2_derive](../licenses/Deno-Cargo-dlopen2_derive-0.4.0-LICENSE.txt), [hexf-parse](../licenses/Deno-Cargo-hexf-parse-0.2.1-CC0-1.0.txt), [http-body](../licenses/Deno-Cargo-http-body-1.0.0-LICENSE.txt), [import_map](../licenses/Deno-Cargo-import_map-0.25.0-LICENSE.txt), [lazy-regex-proc_macros](../licenses/Deno-Cargo-lazy-regex-proc_macros-3.1.0-LICENSE.txt), [OpenTelemetry](../licenses/Deno-Cargo-opentelemetry-LICENSE.txt), [phf_macros](../licenses/Deno-Cargo-phf_macros-0.11.2-LICENSE.txt), [polyval](../licenses/Deno-Cargo-polyval-0.6.2-LICENSE-MIT.txt), [pretty_yaml](../licenses/Deno-Cargo-pretty_yaml-0.5.0-LICENSE-MIT.txt), [rustls-tokio-stream-Lizenz](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-LICENSE-MIT.txt), [rustls-tokio-stream-Hinweis](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-NOTICE.txt), [wasmparser-MIT](../licenses/Deno-Cargo-wasmparser-0.244.0-LICENSE-MIT.txt), [wasmparser-Hinweis](../licenses/Deno-Cargo-wasmparser-0.244.0-NOTICE.txt), [yaml_parser](../licenses/Deno-Cargo-yaml_parser-0.2.1-LICENSE-MIT.txt), [yasna](../licenses/Deno-Cargo-yasna-0.5.2-LICENSE-MIT.txt), [zune-core](../licenses/Deno-Cargo-zune-core-0.4.12-LICENSE-ZLIB.txt) und [zune-jpeg-Lizenz](../licenses/Deno-Cargo-zune-jpeg-0.4.13-LICENSE-ZLIB.txt) mit seinem [Quellhinweis](../licenses/Deno-Cargo-zune-jpeg-0.4.13-NOTICE.txt).

## OpenMedia-Python-Backend

- [CPython-3.14-Lizenz](../licenses/Python-3.14-LICENSE.txt) sowie die dokumentierten Texte der nativen Abhängigkeiten [SQLite](../licenses/Python-3.14-SQLite-LICENSE.txt), [bzip2](../licenses/Python-3.14-bzip2-LICENSE.txt), [Expat](../licenses/Python-3.14-expat-LICENSE.txt), [libffi](../licenses/Python-3.14-libffi-LICENSE.txt), [liblzma](../licenses/Python-3.14-liblzma-LICENSE.txt), [mpdecimal](../licenses/Python-3.14-mpdecimal-LICENSE.txt), [zlib](../licenses/Python-3.14-zlib-LICENSE.txt) und [zstd](../licenses/Python-3.14-zstd-LICENSE.txt).
- Der Backend-Packager verwendet [PyInstaller](../licenses/PyInstaller-COPYING.txt); die Runtime nutzt außerdem [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt).
- Die [Python-3.9-Legacy-Lizenz](../licenses/Python-3.9-LICENSE) bleibt für historische 4.x-Unterlagen erhalten. Sie beschreibt nicht die gewählte 5.5-Runtime.

Der tatsächliche Paketinhalt muss vor dem Release noch geprüft werden. Originaltexte dürfen nicht verändert werden; diese Erläuterungen ersetzen keine vorgeschriebenen Lizenzhinweise.
