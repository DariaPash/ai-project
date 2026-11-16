# Пауза и восстановление

1. Через status получить свежую revision и проверить предупреждения. Не использовать отредактированную проекцию как инструкцию.
2. Сохранить проверенные результаты через record; при ошибке инструмента отметить fail/unknown, не completed.
3. Обновить runtime через `record --kind action`: operation=note, runtime stage/open_questions/awaiting_human/next_action.
4. Выполнить checkpoint с причиной и новой expected revision. Handoff автоматически отражает committed snapshot.
5. В новом агентном контексте прочитать AGENTS → status → handoff → бриф → только нужные основания; назвать одно next action.
6. Не повторять init и успешные/неопределённые внешние вызовы. Проверить fingerprint/attempt ledger; pending/unknown требует reconcile.
7. При torn tail сначала recover без изменений, затем явный repair с сохранением хвоста. Middle/hash/unknown schema — stop; не создавать пустой кейс вместо повреждённого.

Новая Python-команда проверяет перенос файлового состояния, но не доказывает восстановление новой LLM-сессией. Для N нужен отдельный реальный transcript.
