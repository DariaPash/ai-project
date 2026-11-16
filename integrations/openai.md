# OpenAI: через существующую подписку OpenCode, не через новый API key

## Onboarding без скрытого состояния автора

Локальные чтение/расчёт/генератор читаемых proposal работают без модели. Для
model task сначала нужна отдельная настройка runtime/permissions/budget в новой
среде; наличие переменной ключа или sign-in не заменяет согласие. Bootstrap
команды пока pending integration: см. фактический `integrations/bootstrap.md` и
проверенный help после интеграции. Старый `.local/subscription-budget.json` нельзя
выдать новому пользователю как его баланс. Не копируйте OAuth/API secrets.

Исторические разрешения ниже принадлежат конкретному development scope, не всем
читателям пакета. Разрешена текущая `codex/gpt-6.1-sol` через существующий OpenAI;
другие модели/providers не подключались этим изменением. Сеть/оплата/публикация
генератору v4 не требуются и не выполняются.

Владелец разрешил текущий OpenAI-провайдер OpenCode и лимит$100 по самостоятельно
считаемому API-эквиваленту токенов. Настоящий вызов уже выполнен через
`tools/adapters/opencode_model.py`: отдельная host session, сохранённый raw response,
RTE-002 и reconciliation без повторной генерации. Подробности — `host.md`.

Официальные rates gpt-6.1-sol прочитаны со страницы OpenAI API pricing. Для budget
guard используются более высокие long-context rates и reasoning over-count,
дополнительные неизвестные расходы резервируются, не считаются нулевыми.
Расход ChatGPT quota нельзя достоверно вывести из этих rates; OAuth credentials
не извлекаются. Actual transient tokens сервер не сообщил — полный$10 reserve удержан.

## Отдельный API-key adapter

Для отдельного вызова api.openai.com по API key нет отдельного согласованного
credential/endpoint scope. Он не нужен для уже работающего OpenCode-пути.
Ключи не читались, запросы/платежи не выполнялись. module model_openai возвращает
MODEL_API_BLOCKED — это **не реализованный API adapter и не live capability**.
Работающий разрешённый путь отдельного review — host bridge. API adapter можно
реализовывать после доступной актуальной спецификации и scoped разрешения;
не подставлять выдуманный response/model ID или цену.
