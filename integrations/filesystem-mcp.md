# Filesystem MCP — настоящий локальный read/import

## Первая установка в новой папке

Локальное ядро и CLI ingest не требуют MCP. Исторический success ниже не
доказывает наличие Node/SDK/server на машине читателя. Не копировать авторский
runtime config с абсолютным Homebrew-путём. Bootstrap inspect/setup готовится
отдельным исправлением: до проверки help точные команды не заявлены. Настройка
должна выбрать реально найденный executable, фиксированную версию server/SDK,
dedicated root и pinned hashes. Установка требует отдельного разрешения registry;
никакого `npx latest` и автоматического расширения HOME/network/write scope.

По разрешению владельца установлены project-local официальный
`@modelcontextprotocol/server-filesystem==2.3.0` и Python SDK `mcp==2.3.0`.
Настоящие initialize/list_tools/read_text_file выполнены. SRC-016/EXT-018 импортированы
через MCP; ordinary CLI fallback того же файла сохранил тот же SRC-016. После
статического review fixes новый рабочий материал импортирован как SRC-017/EXT-020,
content receipt сохраняет synthetic origin и source parent.

`mcp probe --case ID --spec FILE --expected-revision R`, spec:
`{"root":"cases/ID/input/mcp-materials"}`. Возвращает persisted probe receipt и
реальные имена read tools. `mcp call` принимает root/probe_ref/tool/path/ingest
(`schemas/mcp-request.schema.json`). Имя выбирается только из actual catalog.

Права: единственный выделенный input/mcp-materials root этого case, descriptor-safe
pre/post input hash, UTF-8 TXT/MD до64KB. Write/delete запрещены клиентом, независимо
от того, что сервер рекламирует. Node процессу запрещена сеть. Runtime hashes pinned.
Schema digest проверяется до tool call. Pending/unknown external operation identity
не обходится сменой title, probe_ref, alias или кода; metadata не разрешает повтор.

Первый probe завершился SDK field-name mismatch: legacy camelCase исправлен на
реально осмотренные v2 next_cursor/input_schema. Failure и unknown read-only outcome
сохранены, не названы успехом. Тогда controlled outage/negative scenarios не
запускались по историческому запрету. Сейчас технические тесты исправлений
разрешены, benchmark запрещён; закрытие новых проверок — только по новым receipts.
Полная security acceptance не заявлена.

## Историческое состояние до разрешения на установки

Node установлен, но официальный filesystem server и Python MCP SDK не найдены
в разрешённо осмотренных известных roots. Пакеты не устанавливались; `npx latest`
не используется. Live initialize/list/schema/read **не выполнялись**.

Раньше `mcp probe|call` сохранял denied/unavailable ошибку и не запускал непроверенный
entrypoint и не расширяет права. Пока нет фактического list_tools/schema нельзя
доверять имени read tool из конфигурации; write/delete запрещены.

Рабочий fallback: обычный `ingest` того же разрешённого локального файла через
Source/Extraction pipeline. Он не становится MCP и не снимает F12 live gate.
Для полного stdio пути нужны одобренная установка фиксированной версии
`@modelcontextprotocol/server-filesystem`, SDK и отдельный ограниченный root.
Один permission filesystem read не разрешает HOME, write или API upload.
