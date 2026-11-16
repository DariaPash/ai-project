# Перенос собственного учебного кейса с отдельным согласием

Исторические `source.rights.external_transfer=false` не переписываются.
Дополнительное real APR scope=data_transfer связывает exact source revisions/hashes,
неизменяемое предложение, человеческий ответ и точный destination root.
Это право локального копирования истории; в Codex разрешён только обезличенный
синтетический текст, не raw audio/video. Публикация и business-H не разрешаются.

```sh
python -m tools.cli export --case test-core --mode backup --out output/backups/codex-v1.zip --approval APR-ID --destination /absolute/local/project
python -m tools.cli import-case --case test-core --namespace test --bundle input/backups/codex-v1.zip --authorization-project /absolute/original/project --approval APR-ID
```

Import запускается в destination root. Original project указывается явно как
доверенный локальный источник: проверяются committed APR, source inventory и
неизменяемый export receipt вне ZIP, связывающий архив, snapshot и destination.
Редактируемый manifest ZIP не может сам разрешить передачу. Архив сначала
проверяется в staging; namespace/refs/history сохраняются, overwrite запрещён.
Capabilities, credentials, environments и locks не переносятся. Это не универсальная
подписанная межмашинная авторизация: этот scoped-owner путь требует исходный Store.

Без этих флагов сохраняется прежний same-root backup receipt path. Public export
всегда отдельно требует publication rights на все источники.

## Независимое локальное восстановление опубликованного synthetic demo

Python interface:

```python
import_case(project, "input/backups/demo.zip", "test-core", "test",
            trusted_bundle_sha256=verified_digest_from_user)
```

`trusted_bundle_sha256=None` по умолчанию сохраняет прежние проверки. Новый аргумент
— **явное локальное согласие пользователя на обработку точных bytes**, а не право,
выданное ZIP. Полный lowercase SHA-256 всего архива нужно получить вне архива из
проверенного пользователем источника (например, digest конкретной одобренной версии
в release README). Нельзя автоматически брать его из manifest или считать простой
самостоятельный расчёт digest согласием. CLI-флаг `--trusted-bundle-sha256` подключается
отдельно в CLI; Python-параметр не меняет существующие команды.

Digest сверяется **до staging и любых записей**. Затем проверяются ZIP caps, member
hashes, committed Store, прежний namespace, refs, вся история и diagnostic quarantine.
Shortcut разрешён только при наличии источников, когда **каждая историческая версия**
имеет `origin=synthetic_fixture`, `rights.processing=true` и не наследует real/unknown
provenance. Это не разрешение для real-source/raw private data; автоматическая проверка
метаданных не удостоверяет правдивость маркировки или личность правообладателя.
Никакие исторические rights не переписываются; model transfer, публикация и H
**не разрешаются**. `--authorization-project`/`--approval` с digest не совмещаются.

До установки сохраняется immutable локальный receipt
`.local/import-consents/<archive-sha256>.json`: archive/snapshot/inventory digests,
namespace, destination-root hash и исключительно local-processing scope. Receipt не
попадает в export, не заменяет APR и не используется как внешнее разрешение. Он
фиксирует согласие на restore, а не успешное завершение установки.

Полный image с пересозданными projections проверяется под destination root в
`.local/import-staging/<unique-id>/`, затем под target lock атомарно переносится
**одним no-overwrite rename на той же файловой системе**. macOS использует
`renameatx_np(RENAME_EXCL)`, Linux — `renameat2(RENAME_NOREPLACE)`; без гарантированной
поддержки операция blocked, небезопасного fallback нет. Сбой до promotion оставляет
только staging, не частичный accepted case. Staging сохраняется для диагностики;
автоматического удаления или resume нет. Ошибка fsync после promotion означает
неизвестную durability полного кейса: сначала проверить target, не повторять вслепую.
