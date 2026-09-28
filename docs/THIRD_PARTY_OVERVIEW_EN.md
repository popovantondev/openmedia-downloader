# Third-party components and license index

This index explains the third-party license files kept in [`licenses/`](../licenses/). It does not replace them: upstream license and copyright texts are preserved in their original wording. The presence of a file here does not by itself prove that the corresponding code is linked into a particular app build.

**Distribution is blocked.** Deno notice/linkage, native source and build provenance, and final packaged-component checks remain open. See [rights and release status](RIGHTS_EN.md). The detailed internal audit is not part of the public documentation set.

## yt-dlp standalone package

The bundled yt-dlp executable is an upstream PyInstaller build with additional components. Its upstream files and related notices are:

- [yt-dlp source license](../licenses/yt-dlp-LICENSE), [bundled third-party license collection](../licenses/yt-dlp-THIRD_PARTY_LICENSES.txt), and [GPL version 3 text](../licenses/GPL-3.0.txt).
- [PyInstaller 6.22.0 notice](../licenses/yt-dlp-PyInstaller-6.22.0-COPYING.txt) and [typing_extensions 4.16.0 license](../licenses/yt-dlp-typing_extensions-4.16.0-LICENSE.txt).
- The bundled OpenSSL 3.5.7 notice uses the same verified text as [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt); the bundled Zstandard notice is included in [Python's zstd license text](../licenses/Python-3.14-zstd-LICENSE.txt).

## curl-cffi native sources

These files correspond to source inputs named by the pinned upstream build recipe. Exact correspondence to the embedded universal2 binary, including patches and compiler settings, is not established.

- [curl-impersonate](../licenses/curl-impersonate-2.0.0-LICENSE.txt), [curl](../licenses/curl-8.21.0-COPYING.txt), [BoringSSL](../licenses/BoringSSL-156c7b75-LICENSE.txt), and [fiat](../licenses/BoringSSL-fiat-LICENSE.txt).
- [Brotli](../licenses/Brotli-1.2.0-LICENSE.txt), [nghttp2](../licenses/nghttp2-1.63.0-COPYING.txt), [nghttp3](../licenses/nghttp3-1.15.0-COPYING.txt), and [ngtcp2](../licenses/ngtcp2-1.20.0-COPYING.txt).
- [zlib](../licenses/zlib-1.3.1-LICENSE.txt) and [Zstandard](../licenses/Python-3.14-zstd-LICENSE.txt).

## FFmpeg and LAME

- [FFmpeg LGPL 2.1 text](../licenses/FFmpeg-8.1.2-LGPL-2.1.txt), [FFmpeg license/notice](../licenses/FFmpeg-8.1.2-LICENSE.md), and [LAME COPYING](../licenses/LAME-3.100-COPYING.txt).

## Deno, RustyV8, V8 and web/runtime types

- Main notices: [Deno](../licenses/deno-LICENSE.md), [RustyV8](../licenses/Deno-RustyV8-150.4.0-LICENSE.txt), [V8](../licenses/Deno-V8-15.0.245.2-LICENSE.txt), [V8 license](../licenses/Deno-V8-15.0.245.2-LICENSE.v8.txt), [fdlibm](../licenses/Deno-V8-15.0.245.2-LICENSE.fdlibm.txt), [Strongtalk](../licenses/Deno-V8-15.0.245.2-LICENSE.strongtalk.txt), [Node types](../licenses/Deno-2.9.6-Node-Types-LICENSE.txt), [Undici types](../licenses/Deno-2.9.6-Undici-Types-LICENSE.txt), and [WebGPU](../licenses/Deno-2.9.6-WebGPU-LICENSE.md).
- Cargo package texts: [Inflector](../licenses/Deno-Cargo-Inflector-0.11.4-LICENSE.md), [aead](../licenses/Deno-Cargo-aead-0.5.2-LICENSE-MIT.txt), [aes-gcm](../licenses/Deno-Cargo-aes-gcm-0.10.3-LICENSE-MIT.txt), [alloc-stdlib](../licenses/Deno-Cargo-alloc-stdlib-0.2.2-LICENSE.txt), [aws-lc-rs](../licenses/Deno-Cargo-aws-lc-rs-1.16.3-LICENSE.txt), [aws-lc-sys](../licenses/Deno-Cargo-aws-lc-sys-0.40.0-LICENSE.txt), [backhand Apache](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-APACHE.txt), [backhand MIT](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-MIT.txt), [bytes-str](../licenses/Deno-Cargo-bytes-str-0.2.7-LICENSE-APACHE.txt), [cranelift-assembler-x64](../licenses/Deno-Cargo-cranelift-assembler-x64-0.117.2-LICENSE.txt), [dlopen2_derive](../licenses/Deno-Cargo-dlopen2_derive-0.4.0-LICENSE.txt), [hexf-parse](../licenses/Deno-Cargo-hexf-parse-0.2.1-CC0-1.0.txt), [http-body](../licenses/Deno-Cargo-http-body-1.0.0-LICENSE.txt), [import_map](../licenses/Deno-Cargo-import_map-0.25.0-LICENSE.txt), [lazy-regex-proc_macros](../licenses/Deno-Cargo-lazy-regex-proc_macros-3.1.0-LICENSE.txt), [OpenTelemetry](../licenses/Deno-Cargo-opentelemetry-LICENSE.txt), [phf_macros](../licenses/Deno-Cargo-phf_macros-0.11.2-LICENSE.txt), [polyval](../licenses/Deno-Cargo-polyval-0.6.2-LICENSE-MIT.txt), [pretty_yaml](../licenses/Deno-Cargo-pretty_yaml-0.5.0-LICENSE-MIT.txt), [rustls-tokio-stream license](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-LICENSE-MIT.txt), [rustls-tokio-stream notice](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-NOTICE.txt), [wasmparser MIT](../licenses/Deno-Cargo-wasmparser-0.244.0-LICENSE-MIT.txt), [wasmparser notice](../licenses/Deno-Cargo-wasmparser-0.244.0-NOTICE.txt), [yaml_parser](../licenses/Deno-Cargo-yaml_parser-0.2.1-LICENSE-MIT.txt), [yasna](../licenses/Deno-Cargo-yasna-0.5.2-LICENSE-MIT.txt), [zune-core](../licenses/Deno-Cargo-zune-core-0.4.12-LICENSE-ZLIB.txt), and [zune-jpeg license](../licenses/Deno-Cargo-zune-jpeg-0.4.13-LICENSE-ZLIB.txt) plus its [source notice](../licenses/Deno-Cargo-zune-jpeg-0.4.13-NOTICE.txt).

## OpenMedia Python backend

- [CPython 3.14 license](../licenses/Python-3.14-LICENSE.txt), plus the recorded native dependency texts for [SQLite](../licenses/Python-3.14-SQLite-LICENSE.txt), [bzip2](../licenses/Python-3.14-bzip2-LICENSE.txt), [Expat](../licenses/Python-3.14-expat-LICENSE.txt), [libffi](../licenses/Python-3.14-libffi-LICENSE.txt), [liblzma](../licenses/Python-3.14-liblzma-LICENSE.txt), [mpdecimal](../licenses/Python-3.14-mpdecimal-LICENSE.txt), [zlib](../licenses/Python-3.14-zlib-LICENSE.txt), and [zstd](../licenses/Python-3.14-zstd-LICENSE.txt).
- The backend packager uses [PyInstaller](../licenses/PyInstaller-COPYING.txt); the runtime also uses [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt).
- [Python 3.9 legacy license](../licenses/Python-3.9-LICENSE) is retained for historical 4.x records and does not describe the selected 5.5 backend runtime.

The package inventory and actual build contents still require release verification. Preserve every upstream text exactly; explanations here are not substitutes for legal notices.
