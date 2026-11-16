# Стратег с проверяемыми основаниями — локальное ядро и аналитика

Папка агента IDE: LLM выбирает действия, CLI проверяет и сохраняет данные. Реально
использованы локальные источники/расчёты, research/strategy contracts, OCR/video,
локальная расшифровка whisper.cpp, отдельный reviewer, filesystem MCP и512d hybrid
память. Прямой bounded model task доступен через существующую OpenCode/ChatGPT
подписку; новых API-ключей не нужно. CLI сам не принимает бизнес-решение за человека.
Реальный перенос и одно текстовое продолжение в Codex выполнены на том же компьютере
по отдельному согласию; это не проверка другой ОС. Полная приёмка F01–F15,
listening verification и реальные бизнес-H не закрыты.

**Политика исправлений v4: технические, regression, clean-install и integration
тесты разрешены; benchmark по-прежнему запрещён.** Исторические результаты не
принимают новые изменения автоматически. В v4 исправляется onboarding; готовность
нового комплекта не объявляется до проверки точных файлов.

Локальный v4: новая PTY-запись 304,72с с настоящим отдельным контекстом синтеза,
новые STR-001@5/STR-002@5 в отдельной учебной ветке и полный иллюстрированный PDF.
Общая техническая регрессия: 345 passed; это не полная F01–F15 acceptance и не
benchmark. Точные assets, hashes и пределы — во внешнем release manifest v4.

Актуальные интеграции: `integrations/host.md`, `integrations/filesystem-mcp.md`.
Опубликованный [демокомплект v3](https://github.com/DariaPash/ai-project/releases/tag/demo-v3):
183,28с настоящей PTY-записи, PDF8страниц/8скриншотов, исходники и синтетический кейс.
Локальные ссылки и пределы — `submission/PUBLISHED_V3.md`; прежний v2 сохранён.
Это историческая публикация v3: её bytes/receipts не переписываются. Новый v4 пока
не опубликован и не одобрен по точным hashes. Google Drive выбран для видео, но
не подключён, ничего туда не загружено и anonymous playback не проверен.
Юридическая отправка не выполнена; её делает капитан.

## Локальное ядро: запуск без development fixtures

Рабочая проверенная конфигурация: CPython 3.14.8, macOS arm64, локальный POSIX filesystem. Заявленная база Python ≥3.11 не означает проверку всех версий/ОС. На Windows безопасный fd/lock-путь пока unavailable; сетевые filesystems не поддерживаются.

Из корня проекта, **не переиспользуя пользовательскую `.venv`**:

```sh
python3 -m venv .venv-dev
.venv-dev/bin/python -m pip install -r requirements.txt
.venv-dev/bin/python -m pip install --no-build-isolation -e .
.venv-dev/bin/python -m tools.cli doctor
```

Первую команду выполнять только если `.venv-dev` ещё нет; существующее окружение сначала осмотреть. Ключи/оплаченные сервисы не нужны. Фиксированные версии — результат наблюдаемой установки, а не обещание доступности на любой платформе.

Установка зависимостей требует доступа к registry и отдельного разрешения: эти
команды не являются разрешением сети или расходов. При уже установленном окружении
начните с `doctor`. Он не устанавливает пакеты и не делает live-probe. Диагностика
другой машины не наследует успешные receipts авторского Mac. См. `integrations/`.

## Минимальный технический старт (не бизнес-решение)

```sh
.venv-dev/bin/python -m tools.cli init --case test-quickstart --namespace test
.venv-dev/bin/python -m tools.cli status --case test-quickstart
.venv-dev/bin/python -m tools.cli validate --case test-quickstart
```

Этот путь создаёт и читает пустой test-кейс; он не запускает исследование и не
зависит от `tests/` или `planning/`. Не повторяйте `init` поверх существующего кейса.
Для содержимого сохраните свой JSON request в `cases/test-quickstart/input/` по
схемам `schemas/`; пример ниже. Mutation требует revision из свежего `status`,
а не числа из чужого примера. `demo`/`official` требуют отдельных D/B gates.

Самодостаточный вход брифа (сохранить как `cases/test-quickstart/input/brief.json`):

```json
{"payload":{"goal":"Проверить, стоит ли улучшать ручную проверку итогов встречи","constraints":["Только учебные данные; без сети и реальных клиентов"],"open_questions":["Что именно задерживает передачу итогов?"]}}
```

Затем `record --case test-quickstart --kind brief --file
cases/test-quickstart/input/brief.json --expected-revision R` с фактическим `R`.
Это JSON-данные, не команда запуска модели. При отсутствии папки `input` создайте
её обычным файловым инструментом; не копируйте developer fixtures.

## Переносимый комплект v4: контракт упаковки, ещё не release

Состав локального кандидата: `project/` (код, schemas/config/workflows/knowledge/skills/
integrations), `project/input/backups/demo.zip`, `readable-case/`, `START_HERE.md`.
Production-инструкции не требуют `planning/`, test fixtures, `.local` автора или
его абсолютных путей. Независимый от исходного Store clean-install/import,
checkpoint и продолжение новым процессом проверены. Итоговая проверка точных
байтов и внешние ограничения перечислены в release manifest, не скрыты этим текстом.

Читаемые предложения готовит `submission/prepare-v4-readable.py --project
STORE_ROOT --case test-core --out NEW_DIRECTORY`: явный корень Store, новая
папка, без сети/модели/мутаций. Собственный synthetic кейс можно выбрать только
явным `--local-case-location submission/local-case-location.json`; внутри пакета
используйте `helpers/prepare-readable.py --project . --out NEW_DIRECTORY`, а не
developer pointer. Каталог точных переводов поставляется рядом с helper.
Перевод привязан к hash payload;
изменившиеся ревизии отмечаются translation gap, не получают старый перевод.

Независимый локальный импорт собственного synthetic backup с заранее известным
**вне ZIP** SHA-256 выполняется флагом `--trusted-bundle-sha256`; точная команда
и digest находятся в `START_HERE.md` уровнем выше project. Это только
локальное доверие к точным bytes: не разрешение external/model/publication и не
изменение исторических source rights. Сохранённый внутри ZIP hash не доверенный.
Bootstrap inspect/setup реализован; точные команды и явные разрешения —
`integrations/bootstrap.md`. `python -m tools.bootstrap inspect` не скачивает и
не вызывает модели. Новая машина не наследует успешные runtime receipts автора.

## Реализованные команды и данные

`python -m tools.cli --help` и help каждой группы показывают фактические аргументы. Даже help/ошибки argparse — один JSON stdout. Формат: `ok, code, action_id, attempt_id, case_revision, data, warnings, error`; при ошибке reason/saved/next_action. Diagnostics — stderr без исходного untrusted payload.

- `init --case ID --namespace test|demo|official`: без overwrite.
- `status --case ID`, `validate --case ID`: чтение committed snapshot; validate — **структурная**, не смысловая проверка.
- `record --case ID --kind KIND --file JSON --expected-revision R`: файл `{"payload": {...}, "id": "optional existing ID", "created_by": "optional label"}`. Исходные kinds: brief/question/claim/link/option/strategy/promise/experiment/decision/action/permission. Реальные формы payload — `schemas/*.json`. Дополнительные BRF/STR/PRM/PER IDs обозначают бриф/стратегию/обещание/разрешение; основные IDs исходного плана сохранены.
- `approval request|record --case ID --file JSON --expected-revision R`: APR с exact targets/digest и terms; response требует неизменяемого transcript artifact. Обычный ingest не превращает документ в human approval: human transcript с точным processing_kind регистрируется явно через Store backend.
- `checkpoint --case ID --reason TEXT --expected-revision R`.
- `recover --case ID`: read-only диагноз; `recover --repair-tail --expected-revision R` отдельно сохраняет и удаляет только доказанно незавершённую последнюю строку. Повреждение середины/хеша/неизвестной версии не исправляется сбросом.

Exit codes: 0 success; 2 input/schema/ref; 3 blocked/unavailable/approval/budget; 4 safety/policy; 5 parser/network timeout или временная ошибка, без автоматического повтора; 6 corruption/I/O; 7 revision/lock/existing-case conflict. Внутренний тестовый failpoint завершает процесс кодом97 только в `test-*` с явным test-mode; это не публичный error code.

Пользовательские JSON/материалы размещайте в `cases/<текущий-id>/input` и requests
по фактической policy `config/`; исторические пути `tests/fixtures/` не обязательны
для пользовательского старта. Абсолютные input paths, `..`, symlinks, hardlinks и
special files не принимаются. Материал не становится настройкой доверия. Никаких
секретов в config; fixture origins не переименовывать в real observations.

## Источники и расчёты — шаг 02

- `ingest --case ID --path FILE --spec JSON --expected-revision R`: snapshot bytes через безопасный fd, затем parser subprocess и один COMMIT Source/Extraction/artifacts. Единичный spec — по `schemas/ingest-spec.schema.json`, с собственными разрешёнными данными в case input; development-каталог specs для этого не нужен.
- `search --case ID --query TEXT`: local lexical с pinned Source/Extraction/hash/координатами/цитатой, origin и publication group. **Не web discovery**; `--discovery` → exit3. Статус/processing rights проверяются по текущему snapshot.
- `metrics --case ID --spec JSON --expected-revision R`: cohorts/funnel/segments/economics/scenarios/sensitivity. `schemas/metrics-spec.schema.json`: pinned source+extraction refs, raw hash, таблица, field map, определения. Выбирается вся явно импортированная таблица, не произвольный SQL/код. CAL сохраняет spec, table hashes, exclusions, JSON/CSV и method source hash. Реальные refs берутся из вашего ingest, не из developer fixtures.
- `fetch --case ID --url HTTPS --spec JSON --expected-revision R`: известный URL, **не поиск**. Production default deny. `allowed_domains` принимает `{"host":"example.org","paths":["/exact-path"]}`; wildcard/subdomain/prefix matching нет. Одна запись без реального согласования не разрешает вызов.

| Формат | Локатор и ограничения |
|---|---|
| MD/TXT | Явный encoding; исходные 1-based lines и Unicode char offsets |
| text-PDF | Физическая 1-based page; image-only → exit3/OCR_REQUIRED; сложные таблицы не реконструируются как проверенные |
| CSV | Явные delimiter/header; logical row и физические строки, включая multiline; неоднозначность → exit2 |
| XLSX | Явный sheet/header; cell ranges; ZIP/XML caps; no macros/external links; формулы не вычисляются |
| HTML snapshot | Сохранённые bytes/hash, title, tag/element/id, exact quote; scripts/styles удаляются; JS-only не поддерживается |

Hard caps: input/output ≤8 MiB, rows ≤2000, columns ≤64, PDF pages ≤100, parser ≤10 секунд, ZIP expansion ≤16 MiB и ratio ≤200. Parent убивает зависший parser; POSIX CPU/address-space limits применяются там, где поддержаны. Parser Python audit запрещает network/spawn и сохраняет hashes открытых путей, но **не является OS sandbox или защитой от native exploit**.

Повтор bytes+identity+spec+parser/policy fingerprint возвращает accepted receipt без нового парсинга/SRC/EXT. Changed bytes → SRC revision; другой parser/sheet → новый EXT с прежним SRC при неизменных исходниках/метаданных. Старые locators неизменны. Одинаковые bytes разных публикаций могут разделять raw ART; разные hashes сами по себе не доказывают независимость публикаций.

Retention: явные as_of/date-format/UTC и полное календарное окно; молодые исключены, zero denominator=null. Funnel требует отдельный activation window и упорядоченные события. Дубли/пропуски отражены отдельно. Экономика — Decimal, единая валюта/месячный период. Missing formula cache → exit3; opt-in `allow_cached_with_warning` не проверяет свежесть кэша. CSV экранирует formula injection; raw значения остаются в JSON.

Fetch требует current real source-access APR с `terms.urls` (точные URL), `processing=true`, `expires_at` с timezone, а также PER на external source_access/development_resource с реальным ресурсным APR и caps. Fixture APR никогда не разрешает сеть. Только HTTPS:443, ASCII/IDNA hostname, без userinfo/query/fragment/encoded-path ambiguity/proxy/cookies/auth/JS. Все DNS answers global; IPv4-mapped нормализуются, переходные IPv6 запрещены. Numeric socket pin + SNI/Host/cert/peer verification; каждый redirect проверяется заново. Identity encoding, streaming cap и общий worker deadline. Intent до вызова; settlement после; reserved/outcome_unknown требуют reconcile. Автоповтора/refresh завершённого URL нет.

**Live fetch не выполнялся:** allowlist пуст и real approvals отсутствуют. Security tests используют обозначенные doubles, не живой TLS. Локальный synthetic smoke, текущая агентная самопроверка конфликта и process-level audit traces — `planning/evidence/02/`; все F01–F15 целиком не объявлены готовыми.

## Текстовый research/strategy workflow — шаг 03

`record --kind` дополнен `research_plan` (RPL), `interview_guide` (IGD),
`interview_analysis` (INA), `simulation` (SIM). Оркестратора/agent loop нет:
LLM среды создаёт содержимое, CLI проверяет schema/refs/digests и сохраняет.
Существующие OPT/STR/DEC IDs и record schema_version=1 не меняются.

Новые payloads используют **contract_version=3**: `schemas/research.schema.json`,
`interview.schema.json`, `simulation.schema.json`, `strategy.schema.json`.
Старая committed history читается без rewrite. Legacy writes сохранены только для
core test-* без RPL; RPL включает строгий профиль. V3 entity нельзя downgrade
даже до плана; новые demo/official business records — v3.

- RPL pin QST minimal evidence/stop/outcome и критерии/шкалы/веса/sensitivity до OPT.
  `result` требует basis refs, иначе честный open/gap.
- INA pin corpus/guide/plan, тему с двумя exact quotes разных sources, distinct
  counterexample, interpretation/alternative/real validation. Real interview требует
  real consent на exact corpus и processing; учебный — `fieldwork_conducted=false`.
- SIM pin immutable JSON transcript, execution_id, role conditions/unknowns,
  alternating turns, objections/real validation, mode/model/time/usage. Fixture
  mode — только test; host_inline — actual turns ведущего host в одном контексте,
  не независимые роли/API-вызовы. ACT note/reservation — не исполнение диалога.
  Validator проверяет согласованность receipt, не личность provider криптографически.
- Host execution появляется в usage.jsonl раз на execution_id. При связи с succeeded
  adapter attempt host row reference-only, деньги — из adapter ledger. Fixture turns
  не считаются настоящими вызовами. Unknown money/tokens/human time — null+reason;
  известная стоимость требует amount/currency.
- option_choice APR pin четыре OPT разных типов + RPL и selected OPT в terms:
  `{"contract_version":3,"research_plan_ref":REF,"selected_option_ref":REF}`.
  Criteria/options входят в target digest. Нет ответа → awaiting_human/checkpoint;
  reject/revise — сохранённый отказ, не approve.
- После первого H STR product+communication pin selected OPT/choice, exact UTF-8
  ART text/hash и JSON manifest ART с type/choice/basis/sections/hash. Оба ART
  наследуют evidence parents; другой ART с теми же bytes не очищает synthetic root.
- EXP unknown baseline=null+reason; assumption не measured. Measured baseline
  требует reviewed supported real-world fact CLM с located measurement evidence,
  не unverified/hypothesis/disputed/retracted claim.
- DEC pin первый choice APR, selected/остальные три OPT, обе разнотипные STR,
  PRM matrix и EXP. Второй H final_decision pin exact pending DEC, без скрытого
  business content в terms. Правка содержания требует нового proposal/согласования.
  Fixture approve никогда не реальное H.

`interviews/`, `simulations/`, `decisions/`, `output/research-plan.md`, `options.md`,
`situation.md`, обе стратегии и validation plan — восстановимые проекции. Output
стратегии выбираются по **pinned DEC refs**, не произвольной latest STR.
Процедуры — `skills/interviews.md`, `skills/synthetic-respondents.md`; шаблоны
не заменяют результаты. Нейтральность guide, смысл темы/контрпримера, четыре
механизма и false planned→available promise требуют смыслового review, не validate.
Development review отдельным context выполняется по просьбе пользователя;
runtime reviewer API и полная F07/F11 acceptance — шаг 05+. Host-путь без реального
выбора останавливается на option_choice; полный fixture путь не бизнес-решение.

## Медиа и UX — шаг04, частично

`ingest` принимает `format=image|scan_pdf|audio|video` по
`schemas/media-spec.schema.json`. Это тот же Source/Extraction/ART путь, не отдельный
демонстратор. Нужен единичный spec на разрешённый файл, не каталог developer tests.

- PNG: Tesseract text/confidence/bbox в top-left pixels. Scan PDF: Poppler render
  выбранных физических страниц, text layer не используется, PNG children с dpi/pages.
- PCM16 mono16kHz WAV: исторический Apple Speech probe был blocked без OS
  authorization. Позднее whisper.cpp v1.9.5/base реально обработал собственный
  учебный WAV (EXT-017); без сети при распознавании. Listening verification,
  критичные числа/отрицания и multilingual accuracy не подтверждены. Установка
  модели на другой машине требует отдельных ресурсов/прав, не developer paths.
- MP4: FFmpeg/ffprobe, zero-start CFR, `audio_only`, `sampled_frames` или
  `dense_episode` с явными start/end/interval. Delayed audio явно unavailable;
  WAV duration проверяется по реально извлечённым samples. Frame mapping включает
  requested/actual/offset/frame index/hash/dimensions. Sparse не full coverage.
- Все raw OCR/STT spans uncertain: confidence/малый словарь числительных не
  подтверждает произвольное критичное слово. Такие locators не дают supported fact.
  Отдельная визуальная sample-оценка не редактирует raw OCR.
- `record --kind ux_observation|ux_journey`: pinned image ART/hash, bbox/dimensions,
  visible observation отдельно от hypothesis/test; completion всегда unknown.
  Сам FFmpeg не анализирует изображение: агент должен реально открыть frame bytes.

Проверенные локально версии: Tesseract5.5.3, Poppler26.09.0, FFmpeg/ffprobe9.0.2,
Apple Swift/Speech. `requirements-optional-media.txt` описывает observed prerequisites;
это не install script. Перед установкой/загрузкой отсутствующего движка/voice/model
нужны отдельные R/P. Лицензии engines не передают права на пользовательские media.

Caps: input/output8MiB, pixels4194304, pages10, duration120s, frames64, deadline60s.
Derived file writes имеют POSIX hard file-size cap и остаточный aggregate budget;
read bounded до выделения памяти. Supervisor уничтожает process group по deadline
и после завершения leader. Это не OS-wide sandbox или защита от native exploit.
Swift compiler cache — служебные данные, не derived media; полный scratch/memory
quota требует отдельной проверки и не заявлен по одному output cap.

`doctor --case ID --live formats --approval APR --expected-revision R`: локальные
version/hash diagnostics и существующие receipts разрешённого corpus, не повторная
обработка всех форматов. Ничего не устанавливает/не авторизует; fixture APR test-only.
Owned synthetic TTS/image/video — не полевые интервью или реальные UX наблюдения.

## Маршруты, ревью и явные процедуры — шаг05

Технические тесты исправлений разрешены; benchmark запрещён. Исторический suite
не является приёмкой всех дальнейших изменений. Schema pass не semantic approval.

- `route plan --case ID --spec FILE` выбирает deterministic-first требования,
  не вызывает модель. Spec/receipt — `schemas/route.schema.json`.
- `route run ... --expected-revision R` для host сохраняет ACT intent и возвращает
  `dispatch_required=true`: ведущий агент должен действительно вызвать новый
  контекст, Python не выдаёт подготовку за исполнение.
- `route accept --case ID --file RECEIPT --expected-revision R` сохраняет actual
  context/raw response/output+usage и результат structural/quote/value/coverage gates.
  Unknown model/cost остаётся null; отдельная host context не переключает модель IDE.
- `review run --provider host --spec FILE ...` и `review import --file REPORT ...`:
  exact source/strategy bundle, independent context, immutable REV receipt.
  Обнаруженное исправляется новой revision; review не business-H.
- `hook run --case ID --spec FILE --expected-revision R`: explicit events
  post-ingest/pre-release/on-pause/on-new-evidence/procedure с procedure_id/version
  и basis_refs. Это вызов wrapper, **не автоматический IDE hook**.
- `mcp probe|call`: реально проверены initialize/list/read/import официального
  filesystem server 2.3.0/SDK 2.3.0 на выделенном root (EXT-020); CLI ingest —
  отдельный fallback. На новой машине runtime ещё нужно проверить/настроить.

Детали: `integrations/host.md`, `integrations/filesystem-mcp.md`,
`integrations/openai.md`. Отдельный API-key adapter не подключён; filesystem MCP
фактически работал на авторском Mac, не обещан на любой машине. Число calls берётся
из receipts, fixture H и development review не становятся runtime proof задним числом.

## Жизненный цикл и память — шаг06

Быстрый read-only обзор фактического сохранённого кейса:

```sh
.venv-dev/bin/python -m tools.cli status --case test-quickstart
```

Это не сайт/бот: вывод берётся из указанного committed case. Для импортированного
демо укажите его case ID. Автовыбор через developer evidence для старта не нужен.

- `impact --case ID --claim CLM-ID`: bounded registered dependency closure,
  включая обе стратегии/DEC/обязательства. Не автоматическое понимание релевантности.
- `retract --case ID --file REQUEST --expected-revision R`: новая CLM revision
  со status=retracted и reason. История не удаляется; effective resolver помечает
  производные основания непригодными, не подтверждает новое решение.
- `agenda --case ID --as-of ISO8601`: overdue/unassigned/unknown due/missing metric,
  unknown baseline и pending H. Никакого фонового мониторинга или выдуманного success.
- `record --kind obligation|evidence_match`: typed obligations/содержательная
  привязка нового источника к CLM с точной цитатой. Match не автоматически supported.
- `index build --case ID --spec FILE --expected-revision R`: spec
  `{"mode":"hybrid","language":"eng"}`. Реальные установленные Apple
  NaturalLanguage English sentence embeddings revision1/dimension512. Запуск Swift
  под network deny, без скачивания weights/packages/provider API.
- `retrieve --case ID --query TEXT --mode lexical|hybrid [--history]`:
  lexical+cosine+graph RRF(k60), pinned refs/char ranges/lineage и current-status
  filtering. History не отменяет запрет обработки источника. Corpus change требует
  rebuild; checkpoint сам по себе не инвалидирует index. English only, качество
  не измерялось; корректность ответа не следует из места в выдаче.
- `export --case ID --mode backup|public --out output/backups/FILE.zip`:
  ZIP с immutable history/hash manifest, без ключей/locks/machine capabilities.
  backup restricted sources local-only; public требует publication rights.
- `import-case --bundle input/backups/FILE.zip --case ID --namespace test`:
  no overwrite/namespace change; bounded ZIP reading и предварительное восстановление
  истории в staging. Restricted backup требует доверенного local export receipt
  вне ZIP; флаг внутри архива сам не разрешает перенос.

В учебном кейсе созданы реальный index, OBL с unassigned/due unknown/metric null,
impact/agenda и backup. Позднее по отдельному согласию выполнены локальный перенос
и одно продолжение Codex CLI на том же Mac; branches не объединяются автоматически.
Это не доказательство другой ОС, реального бизнес-H или успешного полевого пилота.
Все F01–F15 целиком не объявляются готовыми.

## Хранение и возобновление

`cases/<id>/records/` и `artifacts/sha256/` неизменяемы. `events.jsonl`: ALLOCATE/PREPARE/COMMIT/ERROR с sequence/hash chain; только COMMIT принимает snapshot `journal/<tx>/snapshot.json`. Числовые ID не переиспользуются после aborted allocation. Читатели/писатели используют OS-backed lock и ожидаемую revision; lock по возрасту не удалять.

`state.json`, `sources.json`, `claims.json`, `usage.jsonl`, `brief.md`, `handoff.md` — проверяемые проекции. После post-COMMIT crash известная stale/missing projection восстанавливается checkpoint; повреждённый/неизвестной версии state требует диагностики, а не тихой перезаписи. Это не защита от владельца ОС, подделавшего весь журнал, и не сертифицированная sandbox для PDF/моделей. Изменённое извлечение получает новый EXT ID, а не новую revision старого EXT: локатор не становится неоднозначным после переизвлечения.

В `usage.jsonl` отдельно локальные action receipts и `entry_kind=adapter_attempt` с фактическими сведениями ledger; их нельзя суммировать как два платных вызова. Неизвестные деньги/токены/human time — null + причина. CLI `data.telemetry` — отдельный неперсистентный receipt текущего вызова; `committed_action_id` указывает ранее сохранённую запись, не означает, что сам telemetry UUID уже записан.

Action operations `reserve/settle/reconcile` — **учёт**, не выполнение API. Reserved intent создаётся до внешнего действия; fixture permission не разрешает external=true. Pending/unknown попытку нельзя повторить, сначала receipt/reconcile. Новый resource permission обязан точно совпасть с APR terms (scope/call_limit/external_allowed/money_limit/allow_unknown_money, при денежном лимите currency). Квота считается по APR, не сбрасывается созданием второго PER с тем же подтверждением. Общий денежный лимит нескольких кейсов не гарантируется — платные кейсы под общим лимитом нельзя запускать параллельно.

## Старт агентной сессии

> Прочитай AGENTS.md. Открой технический кейс test-quickstart: прочитай status и handoff, восстанови ровно следующее действие. Действуй по workflows/pause-resume.md; не повторяй успешные операции и не выдумывай согласования.

Для **разработки исходного проекта**, только если development planning включён:

> Прочитай AGENTS.md, planning/README.md и planning/handoff.md. Выполняй только указанный мной файл planning/steps/NN-*.md, проверив prerequisites и evidence.

Новый контекст и отдельный Codex-клиент проверялись исторически, с сохранением
refs и ограничений; это не гарантия автоматического подключения правил во всех
IDE. Пользователь пакета начинает с `status` своего кейса и его handoff, не с
отсутствующего development planning. Инструкции AGENTS для упаковки ведущая сессия
должна согласовать с фактическим составом; исходный root AGENTS здесь не изменён.

## Навигация пользователя

- `schemas/` — фактические контракты входов и records.
- `templates/`, `knowledge/`, `skills/` — формы и методики, не готовое исследование.
- `workflows/` — продуктовый путь и pause/resume.
- `integrations/` — runtime, permissions и ограничения переноса.
- `cases/<id>/handoff.md` — проекция выбранного committed case.

Прочитана разрешённая сохранённая страница задания; отдельный дополнительный
бриф МегаФона не проверен. Исторический v3 опубликован, v4 не опубликован.
Full official fit, real business H, полная acceptance и benchmark не закрыты.
Development-навигация выше не является runtime-зависимостью переносимого пакета.
