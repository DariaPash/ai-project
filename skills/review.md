# review-v5

procedure_id: review; version:5.
Input: exact bundle refs с текстами STR/PRM/capabilities, без истории автора.
Procedure: `review run --provider host --spec FILE` сохраняет dispatch ACT.
Ведущий host фактически вызывает новый контекст с agents/reviewer.md; сохраняет
raw tool response, context ID, input digest, output и exposed usage (иначе null).
`route accept` принимает факт выполнения; `review import` принимает неизменённый
нормализованный JSON finding. Исправление — новая revision и новый отдельный recheck.
Output: RTE+REV с pinned targets/evidence/limitations, отдельно от business-H.
Invocation: explicit hook procedure review/version5 с RTE/REV refs.
Stop: нет isolated context/реального receipt — unavailable; self-review не independent.
Ревьюер читает переданный результат и не запускает тесты/сеть. Ведущий агент может
отдельно выполнить разрешённые технические проверки; они не заменяют независимое ревью.
