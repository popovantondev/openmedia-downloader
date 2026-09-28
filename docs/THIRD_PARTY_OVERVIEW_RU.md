# Сторонние компоненты и указатель лицензий

Здесь объясняется, какие тексты лицензий сторонних компонентов находятся в каталоге [`licenses/`](../licenses/). Этот обзор не заменяет их: исходные тексты лицензий и авторских уведомлений сохранены без изменений. Наличие файла в списке само по себе не доказывает, что соответствующий код включён в конкретную сборку приложения.

**Распространение заблокировано.** Остаются открытыми уведомления и связь объектов Deno, происхождение нативных исходников и сборок, а также проверка итогового приложения. См. [права и статус выпуска](RIGHTS_RU.md). Подробный внутренний аудит не относится к публичной документации.

## Автономный пакет yt-dlp

Встроенный исполняемый файл yt-dlp — upstream-сборка PyInstaller с дополнительными компонентами. Связанные исходные лицензии и уведомления:

- [Лицензия исходников yt-dlp](../licenses/yt-dlp-LICENSE), [набор лицензий сторонних компонентов](../licenses/yt-dlp-THIRD_PARTY_LICENSES.txt) и [текст GPL версии 3](../licenses/GPL-3.0.txt).
- [Уведомление PyInstaller 6.22.0](../licenses/yt-dlp-PyInstaller-6.22.0-COPYING.txt) и [лицензия typing_extensions 4.16.0](../licenses/yt-dlp-typing_extensions-4.16.0-LICENSE.txt).
- Для встроенного OpenSSL 3.5.7 используется тот же проверенный текст, что и для [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt); уведомление Zstandard включено в [лицензионный текст zstd для Python](../licenses/Python-3.14-zstd-LICENSE.txt).

## Нативные исходники curl-cffi

Эти файлы относятся к исходным архивам из закреплённого upstream-рецепта сборки. Точное соответствие встроенному universal2-бинарнику, включая патчи и настройки компилятора, не установлено.

- [curl-impersonate](../licenses/curl-impersonate-2.0.0-LICENSE.txt), [curl](../licenses/curl-8.21.0-COPYING.txt), [BoringSSL](../licenses/BoringSSL-156c7b75-LICENSE.txt) и [fiat](../licenses/BoringSSL-fiat-LICENSE.txt).
- [Brotli](../licenses/Brotli-1.2.0-LICENSE.txt), [nghttp2](../licenses/nghttp2-1.63.0-COPYING.txt), [nghttp3](../licenses/nghttp3-1.15.0-COPYING.txt) и [ngtcp2](../licenses/ngtcp2-1.20.0-COPYING.txt).
- [zlib](../licenses/zlib-1.3.1-LICENSE.txt) и [Zstandard](../licenses/Python-3.14-zstd-LICENSE.txt).

## FFmpeg и LAME

- [Текст LGPL 2.1 для FFmpeg](../licenses/FFmpeg-8.1.2-LGPL-2.1.txt), [лицензия и уведомления FFmpeg](../licenses/FFmpeg-8.1.2-LICENSE.md), [файл LAME COPYING](../licenses/LAME-3.100-COPYING.txt).

## Deno, RustyV8, V8 и веб-/runtime-типы

- Основные уведомления: [Deno](../licenses/deno-LICENSE.md), [RustyV8](../licenses/Deno-RustyV8-150.4.0-LICENSE.txt), [V8](../licenses/Deno-V8-15.0.245.2-LICENSE.txt), [лицензия V8](../licenses/Deno-V8-15.0.245.2-LICENSE.v8.txt), [fdlibm](../licenses/Deno-V8-15.0.245.2-LICENSE.fdlibm.txt), [Strongtalk](../licenses/Deno-V8-15.0.245.2-LICENSE.strongtalk.txt), [типы Node](../licenses/Deno-2.9.6-Node-Types-LICENSE.txt), [типы Undici](../licenses/Deno-2.9.6-Undici-Types-LICENSE.txt), [WebGPU](../licenses/Deno-2.9.6-WebGPU-LICENSE.md).
- Тексты Cargo-пакетов: [Inflector](../licenses/Deno-Cargo-Inflector-0.11.4-LICENSE.md), [aead](../licenses/Deno-Cargo-aead-0.5.2-LICENSE-MIT.txt), [aes-gcm](../licenses/Deno-Cargo-aes-gcm-0.10.3-LICENSE-MIT.txt), [alloc-stdlib](../licenses/Deno-Cargo-alloc-stdlib-0.2.2-LICENSE.txt), [aws-lc-rs](../licenses/Deno-Cargo-aws-lc-rs-1.16.3-LICENSE.txt), [aws-lc-sys](../licenses/Deno-Cargo-aws-lc-sys-0.40.0-LICENSE.txt), [backhand Apache](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-APACHE.txt), [backhand MIT](../licenses/Deno-Cargo-backhand-0.25.1-LICENSE-MIT.txt), [bytes-str](../licenses/Deno-Cargo-bytes-str-0.2.7-LICENSE-APACHE.txt), [cranelift-assembler-x64](../licenses/Deno-Cargo-cranelift-assembler-x64-0.117.2-LICENSE.txt), [dlopen2_derive](../licenses/Deno-Cargo-dlopen2_derive-0.4.0-LICENSE.txt), [hexf-parse](../licenses/Deno-Cargo-hexf-parse-0.2.1-CC0-1.0.txt), [http-body](../licenses/Deno-Cargo-http-body-1.0.0-LICENSE.txt), [import_map](../licenses/Deno-Cargo-import_map-0.25.0-LICENSE.txt), [lazy-regex-proc_macros](../licenses/Deno-Cargo-lazy-regex-proc_macros-3.1.0-LICENSE.txt), [OpenTelemetry](../licenses/Deno-Cargo-opentelemetry-LICENSE.txt), [phf_macros](../licenses/Deno-Cargo-phf_macros-0.11.2-LICENSE.txt), [polyval](../licenses/Deno-Cargo-polyval-0.6.2-LICENSE-MIT.txt), [pretty_yaml](../licenses/Deno-Cargo-pretty_yaml-0.5.0-LICENSE-MIT.txt), [лицензия rustls-tokio-stream](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-LICENSE-MIT.txt), [уведомление rustls-tokio-stream](../licenses/Deno-Cargo-rustls-tokio-stream-0.8.0-NOTICE.txt), [wasmparser MIT](../licenses/Deno-Cargo-wasmparser-0.244.0-LICENSE-MIT.txt), [уведомление wasmparser](../licenses/Deno-Cargo-wasmparser-0.244.0-NOTICE.txt), [yaml_parser](../licenses/Deno-Cargo-yaml_parser-0.2.1-LICENSE-MIT.txt), [yasna](../licenses/Deno-Cargo-yasna-0.5.2-LICENSE-MIT.txt), [zune-core](../licenses/Deno-Cargo-zune-core-0.4.12-LICENSE-ZLIB.txt), [лицензия zune-jpeg](../licenses/Deno-Cargo-zune-jpeg-0.4.13-LICENSE-ZLIB.txt) и его [уведомление исходников](../licenses/Deno-Cargo-zune-jpeg-0.4.13-NOTICE.txt).

## Python-backend OpenMedia

- [Лицензия CPython 3.14](../licenses/Python-3.14-LICENSE.txt) и тексты лицензий документированных нативных зависимостей: [SQLite](../licenses/Python-3.14-SQLite-LICENSE.txt), [bzip2](../licenses/Python-3.14-bzip2-LICENSE.txt), [Expat](../licenses/Python-3.14-expat-LICENSE.txt), [libffi](../licenses/Python-3.14-libffi-LICENSE.txt), [liblzma](../licenses/Python-3.14-liblzma-LICENSE.txt), [mpdecimal](../licenses/Python-3.14-mpdecimal-LICENSE.txt), [zlib](../licenses/Python-3.14-zlib-LICENSE.txt), [zstd](../licenses/Python-3.14-zstd-LICENSE.txt).
- Для упаковки backend используется [PyInstaller](../licenses/PyInstaller-COPYING.txt); runtime также использует [OpenSSL 3.5.8](../licenses/OpenSSL-3.5.8-LICENSE.txt).
- [Старая лицензия Python 3.9](../licenses/Python-3.9-LICENSE) сохранена для исторических материалов 4.x и не относится к выбранной версии Python для 5.5.

Состав фактического приложения ещё требуется проверить перед выпуском. Не изменяйте оригинальные тексты; этот обзор не заменяет обязательные уведомления.
