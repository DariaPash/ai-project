# Локальная настройка дополнительных возможностей

Основной CLI не требует STT/MCP/OpenCode. Настройка не читает `planning/`,
developer evidence, ключи, OAuth или чужие capabilities. Все команды выполняются
из вашего корня проекта; `--project /absolute/project` можно указать явно.

```sh
python -m tools.bootstrap inspect
```

Это read-only: `implementation`, локальная `availability` и `live_verification`
раздельны. Нет модели/сети/установки; `not_performed` не становится pass по старому
receipt. Доступность не даёт согласия на обработку, передачу или оплату.

## Speech (whisper.cpp)

Нужны уже установленные CMake и C/C++ toolchain. Их автоматической установки нет.
Укажите проверенные upstream version, SHA-256 исходного архива и base-модели,
40-hex immutable revision модели. Значения ниже — переменные оператора, не скрытые
development defaults. Команда ничего не скачает без `--approve-download`.

```sh
python -m tools.bootstrap setup speech --version v1.9.5 \
  --source-sha256 "$WHISPER_SOURCE_SHA256" \
  --model-revision "$WHISPER_MODEL_REVISION" \
  --model-sha256 "$WHISPER_MODEL_SHA256" --approve-download
```

Совместимый entry point: `python -m tools.setup_speech` с теми же speech-аргументами.
Источник — `codeload.github.com/ggml-org/whisper.cpp`; модель —
`huggingface.co/ggerganov/whisper.cpp`, redirects только на явно перечисленные
HF CDN hosts в `tools/bootstrap.py`. Неизвестный CDN блокируется, не разрешается
автоматически. Лимиты: архив 64MiB, распакованные источники 256MiB/20000 entries,
модель 200MiB; download deadline180s (+ текущий socket timeout≤60s), configure120s,
build600s/4jobs, без retries. Профиль `.local/speech-runtime.json` содержит hashes.
Это установка, не проверка качества/прослушивание. Текущий recognition adapter
требует macOS `sandbox-exec`, даже если compilation прошла в другой ОС.

## Filesystem MCP

Нужны Node/npm в PATH и Python SDK `mcp==2.3.0` в выбранном runtime Python.
Для нового isolated runtime (не пользовательской `.venv`):

```sh
python3 -m venv .local/runtime
.local/runtime/bin/python -m pip install -r requirements.txt mcp==2.3.0
.local/runtime/bin/python -m tools.bootstrap setup mcp --version 2.3.0 --approve-download
.local/runtime/bin/python -m tools.bootstrap inspect
```

Команда `pip install` сама явно запрашивает загрузку. Bootstrap не устанавливает
Python-пакеты скрыто. Node обнаруживается динамически и pin-ится с SHA-256;
Homebrew не обязателен. npm получает изолированный HOME/config, exact package,
`--ignore-scripts`, `--no-audit`, `--no-fund`, retry0/timeout180s. npm dependencies
фиксируются package-lock/hash; это не строгая aggregate network-byte/disk quota.
Профиль `.local/filesystem-mcp-runtime.json` не разрешает filesystem scope:
probe/call по-прежнему требуют case-scoped permission и input/mcp-materials.

## OpenCode: только локальный budget bootstrap

Установленный OpenCode должен быть в PATH. Его существующий sign-in используется
адаптером, но bootstrap не читает credentials и вообще не вызывает host API.
Задайте собственные total cap и текущий leader ID. Предыдущий расход **без текущего
leader** укажите положительным upper bound либо явно verified0; unknown требует
положительного резерва. Весь расход текущего leader учитывается от baseline0
при следующем refresh — init не списывает историю в baseline.

```sh
python -m tools.bootstrap budget-init --total-budget 20 \
  --leader-session ses_YOUR_CURRENT_SESSION --prior-consumption-upper-usd 3.5 \
  --approve-local-setup
```

Альтернатива неизвестному расходу:
`--prior-consumption-unknown --unknown-reserve-usd 10` вместо
`--prior-consumption-upper-usd`. `available`/measured usage остаются null до
реального refresh; резерв — не actual charge. Существующий ledger сохраняется
byte-for-byte, **никогда не reset**, включая unknown outcomes. Локальная настройка
не разрешает model call: нужны отдельные approvals и budget refresh перед dispatch.

## Сохранность и границы подключения

Receipts — `.local/bootstrap/{speech,mcp}-install.json`. Ошибки/незавершённые
попытки сохраняются; существующие файлы не перезаписываются. Сначала reconciliation,
не повторная команда с новыми именами. Старые development receipts остаются историей.
SafeRoot запрещает traversal/symlinks/hardlinks; pin не равен защите от враждебного
процесса того же OS user. Не переносите `.local`, budget, capabilities или credentials
в новый проект: новая машина получает новый бюджет/согласования/верификацию.
Новые профили привязаны к local-root device/inode, поэтому копия не наследует их.

Host hooks (обязательны до portable live-заявления): CLI doctor объединяет свои
core поля с `tools.diagnostics.diagnostics(project)["capabilities"]`; MCP adapter должен
использовать `mcp_runtime(project)` и динамический `runtime["node"]`, а OpenCode API
adapter — `opencode_runtime(project)["executable"]` вместо hardcoded Homebrew path.
Speech adapter также должен использовать `speech_runtime(project)`, чтобы новая
root-binding проверялась не только при inspect, но и перед recognition.
Budget refresh должен проверять `local_root` при его наличии и сохранять unknown
usage fail-closed. Старые profiles без binding читаются hash-checked как legacy,
но не являются live proof. Эти hooks не меняют scope или бизнес-H.
