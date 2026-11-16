# Стратег с проверяемыми основаниями — v4

Переносимая папка IDE-агента: LLM исследует и предлагает, Python CLI извлекает,
считает, проверяет ссылки и сохраняет историю. Не автономное приложение.

## Материалы v4

- [Полный комплект с учебным кейсом](https://github.com/DariaPash/ai-project/releases/download/demo-v4/local-demo-kit-v4.zip)
- [Исходники и технические fixtures](https://github.com/DariaPash/ai-project/releases/download/demo-v4/source-kit-v4.zip)
- [Видео, 5:04](https://github.com/DariaPash/ai-project/releases/download/demo-v4/cli-demo.mp4)
- [PDF: 34 страницы, 8 скриншотов](https://github.com/DariaPash/ai-project/releases/download/demo-v4/description-final.pdf)
- [Релиз demo-v4](https://github.com/DariaPash/ai-project/releases/tag/demo-v4)

Те же четыре файла находятся в [`submission/v4/`](submission/v4/).
Хеши — [`submission/v4/release-manifest-v4.json`](submission/v4/release-manifest-v4.json).
Исходники доступны непосредственно в корне; читаемые результаты — в
[`demo/readable-case/`](demo/readable-case/).

Видео — настоящая PTY-запись, не запись рабочего стола: 13 команд, новый отдельный
контекст создаёт две стратегии, Store сохраняет предложения, новый процесс читает
checkpoint. Исторические STT/MCP/Codex-трассы явно отделены от нового выполнения.
Старый одноразовый Codex grant повторно не использовался.

## Быстрый старт исходников

Проверенная среда: CPython 3.14.8, macOS arm64, локальная POSIX filesystem.
Заявленная база Python ≥3.11 не означает приёмку всех версий и ОС.
Не переиспользуйте существующее пользовательское окружение.

```sh
python3 -m venv .venv-dev
.venv-dev/bin/python -m pip install -r requirements.txt
.venv-dev/bin/python -m pip install --no-build-isolation -e .
.venv-dev/bin/python -m tools.cli doctor
.venv-dev/bin/python -m tools.cli init --case test-quickstart --namespace test
.venv-dev/bin/python -m tools.cli status --case test-quickstart
```

Создавайте `.venv-dev` и кейс только при их отсутствии. Установка требует
разрешённой сети; `doctor` не скачивает пакеты и не вызывает модели.
Интеграции подключаются отдельно: [`integrations/bootstrap.md`](integrations/bootstrap.md).
Credentials, пользовательские окружения и machine capabilities не публикуются.

## Восстановление учебного кейса

Скачайте полный комплект, распакуйте в новую папку и откройте `START_HERE.md`.
Команды выполняются из вложенного `project/`, не из исходной машины автора.
Проверенный SHA-256 вложенного `input/backups/demo.zip`:

```text
b2140fc740b6fd38c62f96b8937dd1617f55a821badc3ad91f15cf9ef9873a7f
```

После установки зависимостей:

```sh
python -m tools.cli import-case --case test-core --namespace test --bundle input/backups/demo.zip --trusted-bundle-sha256 b2140fc740b6fd38c62f96b8937dd1617f55a821badc3ad91f15cf9ef9873a7f
python -m tools.cli status --case test-core
```

Используйте Python созданного окружения. Digest — явное доверие только к локальной
обработке собственной синтетики; не разрешение передавать материалы модели или
публиковать свои производные. Исторические rights, namespace и refs сохраняются.
Импорт не перезаписывает существующий кейс.

## Что проверено и что не доказано

- Общий технический прогон: **345 passed**; чистый комплект: ещё **18 passed**,
  editable install, doctor, import, validate, checkpoint, новый процесс и генератор.
- Свежий filesystem MCP bootstrap и настоящий initialize/list/read выполнены.
- Независимое ревью: **acceptable_LOCAL_WITH_EXPLICIT_EXTERNAL_BLOCKERS**;
  [отчёт](submission/v4/final-local-review-reconciled.md).
- **Все данные учебные.** Модельные роли — не клиенты. Реальные спрос, эффект,
  baseline и business-H не установлены; пересмотр остаётся pending.
- Не приняты listening verification STT, другая ОС, качество русского semantic
  retrieval и полный F01–F15 release. Сравнительный benchmark запрещён и не запускался.
- Google Drive не подключён. GitHub-ссылка сама по себе не закрывает требование
  задания о площадке видео. Дополнительный бриф, по сообщению владельца, пока
  не опубликован; это не проверка организатора.

## История и статус

[v3](https://github.com/DariaPash/ai-project/releases/tag/demo-v3) сохранён без изменения
байтов. Внутренние `published=false` и local-only заметки в замороженных архивах v4
относятся к сборке **до этой публикации**; они не переписываются задним числом.
Публичная доступность определяется GitHub и отдельной квитанцией публикации,
а не старым build manifest. Бизнес-согласование и юридическая отправка конкурса
этой публикацией не выполняются: юридически отправляет капитан.

Подробный README состояния сборки сохранён в
[`docs/README-build-v4.md`](docs/README-build-v4.md).
