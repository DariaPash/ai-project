# Процедура: синтетические модельные роли

Input: разрешённый technical corpus (без evaluator key), вопрос решения, role card
с разными условиями и явными known_unknowns, разрешённый host и лимит. Не отправлять
чужие данные другому provider только потому, что есть ключ или подписка.

Ведущий host может исполнить три диалога в одном контексте: руководитель с дефицитом
времени, privacy-constrained исполнитель, закупщик с требованием доказательств.
Для каждой роли последовательно создать вопрос/ответ/уточнение/ответ, сильнейшее
возражение и следующую реальную проверку. Эти turns должны быть фактически
сгенерированы и сохранены с mode=host_inline, model/version если известны, actual
start/end, transcript hash и usage null+reason где неизвестно. Это не независимые
контексты и не реальные респонденты. Не писать готовую fixture simulation за
состоявшийся вызов модели. Mode=fixture проверяет только контракт в test namespace.

Сохранить неизменяемый model-origin JSON transcript и `record --kind simulation`.
Запись ACT note/reservation не доказывает ответ модели. Records удостоверяют
согласованность сохранённого receipt, не личность provider криптографически.
Derived claims/options/strategies/DEC наследуют model_simulation. Нельзя складывать
три роли с тремя интервью, голосованием доказывать спрос, делать H за пользователя
или утверждать эмпирический baseline. Источник истины — исходные данные, не мнение
нескольких модельных персон.

Stop: права/бюджет/host недоступны, unknown outcome, недостаточно входных данных.
Reserved/outcome_unknown сначала reconcile, не повтор. Не запускать autonomous
respondent loop. Output: hypotheses/objections + consent-based field-validation plan.
