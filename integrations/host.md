# Host bridge: рабочая граница

## Новый пользователь и статус v4

Ниже описан фактически выполненный путь авторского Mac, не готовая настройка
любой машины. Для локального ядра достаточно установки из корневого README и
`tools.cli doctor`; модель для status/validate/readable proposal не нужна.
Bootstrap inspect/setup интегрирует другая часть исправлений. До проверки её
реального `--help` точные команды здесь намеренно не выдуманы. Не копируйте
`.local` автора, progress/evidence, host-session IDs, budget ledger или credentials.

Перед первым модельным действием нужны доступный текущий OpenAI sign-in,
подтверждённые provider/data scope, лимит и reservation/receipt, затем runtime
probe. Наличие установленного клиента не разрешает вызов. Текущая модель —
`codex/gpt-6.1-sol` через существующий OpenAI; новые providers/models не добавлены.
Технические тесты разрешены, benchmark запрещён; новое исполнение не нужно для
повторного показа исторического ответа.

## Автоматический путь через текущую OpenCode-подписку

`route run --provider opencode --case ID --spec FILE --expected-revision R`
выполняет один настоящий model task через локальный OpenCode API, используя
существующий вход OpenAI/ChatGPT. Новые API-ключи не нужны и не читаются агентом.
Входы — pinned EXT с текущими processing/external_transfer правами; старые
restricted sources автоматически разрешёнными не становятся. ≤12KB текста,
отдельная host session, transient generate без tools и без повторной генерации
при неизвестном исходе. Успешный результат сохраняется до нормализации.

На установленном OpenCode2.1.4 transient ответ не вернул tokens/cost, несмотря на
опубликованную schema. Текст сохранён, счётчики новой session остались0 и потому
**не использованы как фактический нулевой расход**. До реального подтверждения
стоимости удерживается полный$10 API-equivalent worst-case reserve. Реальный
RTE-002 получен reconciliation сохранённого ответа, без второго model call.

В development-среде `python -m tools.subscription_budget` читает token counters ведущей
сессии и показывает консервативный API-эквивалент дополнительной работы по лимиту
владельца$100. Это не конверсия остатка ChatGPT-подписки в доллары и не гарантия её
доступности. Это developer accounting, не bootstrap для нового пользователя и
не цена одного результата. Ранняя история сохранена; неизвестное не списано в0.

Ни API транспорта, ни schema delivery gates не доказывают полезность ответа.
Semantic/business-H подтверждается отдельно. Путь ограничен текущим codex/gpt-6.1-sol;
на другой машине runtime/provider должны быть реально доступны и разрешены.

## Ручной native-context bridge

CLI не умеет вызывать инструмент native subagent внутри произвольной IDE.
Используется **явный мост ведущего агента**, не fake Python SDK и не subprocess,
выдаваемый за отдельную модель. Изолированные контексты доступны текущему ведущему
через harness; на другой среде capability нужно подтвердить заново.

1. `route plan --case ID --spec FILE`: требования, pinned inputs/digest, без вызова.
2. `route run --case ID --spec FILE --expected-revision R`: сохранённый ACT intent
   и `dispatch_required=true`, **не исполнение модели**.
3. Ведущий агент реально вызывает новый host context с этим bundle, без своей
   истории/секретов. Он не выбирает произвольный model ID без запроса пользователя.
4. `route accept --case ID --file RECEIPT --expected-revision R`: context ID,
   author context, actual raw response/output, timestamps и usage. Неизвестная
   model identity/money/tokens null; actual tool receipt — не криптографическая аттестация.
5. `review import` принимает точный report из route output; новое content — новый
   bundle/dispatch. Approval выбора/DEC не заменяется review verdict.

Одна дополнительная escalation допускается только после failed_quality receipt
и max_escalations=1 исходного intent. Одинаковая default host model не доказывает
экономический выигрыш/переключение «дешёвая→сильная». Честная цена остаётся unknown.
Отдельный API-key вызов к api.openai.com не подключён: согласован existing OpenCode
subscription path, а не копирование OAuth credentials или произвольный endpoint.
