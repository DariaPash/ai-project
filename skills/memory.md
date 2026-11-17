# memory-v6

Input: committed snapshot, pinned refs/current rights. Не брать facts из старого чата.
`impact` — bounded dependency closure, не semantic relevance. `agenda --as-of ISO`
показывает неизвестного owner/due/metric, не выдумывает выполнение.
`index build` сохраняет настоящие installed local Apple English sentence vectors;
`retrieve --mode hybrid` соединяет lexical+cosine+graph RRF, фильтрует текущие права
и withdrawals. Corpus change требует rebuild, checkpoint — нет. Нет модели — blocked,
не random/hash substitute. Retrieval ranks — не supported evidence сами по себе.
Fingerprint включает версию/размер/перекрытие chunker. Индексы до v5 после обновления
требуют явного rebuild; lexical доступен без модели и не вызывает её скрыто.
`retract` создаёт новую CLM revision, не удаляет историю. Новый DEC content требует H.
Backup local-only если external_transfer=false; передача в другой root и публикация
требуют отдельного точного разрешения, успешный restore его не наследует.
Вызов процедуры явно фиксируется hook event=procedure/procedure_id=memory/version6.
Apple English embeddings экспериментальны: качество русского перефразирования
не принято. Для русского текста доступен явный lexical-режим (совпадения слов,
не семантические перефразы). Технические тесты требуют разрешения владельца;
сравнительный benchmark запрещён до отдельного согласования.
