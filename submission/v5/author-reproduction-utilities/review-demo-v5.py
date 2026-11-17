"""Read a saved synthetic case and compute corrections; no new model or business H."""

import json
from pathlib import Path
import subprocess
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.contracts import key
from tools.graph import impact
from tools.option_scoring import scenario
from tools.search import retrieve
from tools.store import Store


def say(value):
    print(textwrap.fill(str(value), width=103), flush=True)


def main():
    mode = sys.argv[1]
    with Store(Path.cwd(), "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        active = lambda identity: records[f"{identity}@{snapshot['active'][identity]}"]
        if mode == "brief":
            say("V5: ИСПРАВЛЕННЫЙ РАЗБОР СОХРАНЁННОГО УЧЕБНОГО КЕЙСА")
            say("Вопрос: улучшить ручную проверку итогов встреч, оставить шаблон, сузить задачу или закрыть?")
            say("Это новый технический прогон, НЕ новая модельная генерация и НЕ независимое ревью.")
            say("Все источники синтетические. Горизонт, бюджет эксперимента и реальный получатель не согласованы.")
            say("Результат: проверяемые расчёты, явные версии предложений и следующий вопрос человеку.")
        elif mode == "sources":
            sources = [
                r
                for r in records.values()
                if r["kind"] == "source" and snapshot["active"].get(r["id"]) == r["revision"]
            ]
            say(
                "Источников: "
                + str(len(sources))
                + "; происхождение: "
                + str(sorted({r["payload"]["origin"] for r in sources}))
            )
            for identity in ("EXT-001", "EXT-004"):
                payload = active(identity)["payload"]
                say(identity + " -> " + key(payload["source_ref"]) + "; source SHA256=" + payload["source_hash"])
                say(payload["text"][:220])
            say("CLM-001@1: создание встречи/24ч и экспорт/7д — разные определения; не объединять.")
        elif mode == "options":
            options = [active(f"OPT-{i:03}") for i in range(1, 5)]
            criteria = records[key(options[0]["payload"]["research_plan_ref"])]["payload"]["criteria"]
            say("Порядок: оставить / улучшить / сменить фокус / закрыть. Точные Decimal-расчёты:")
            for weights in [criteria["weights"], *criteria.get("sensitivity_weights", [])]:
                totals, leaders = scenario(options, weights)
                say("Веса " + "/".join(str(weights[k]) for k in ("privacy", "reversibility", "value")))
                say("; ".join(k + "=" + str(v) for k, v in totals.items()) + "; лидер " + ",".join(leaders))
            say("ОШИБКА V4: 3.3 вместо 3.5 во втором сценарии; смены лидера в этих трёх сценариях НЕТ.")
            say("Это не устойчивость при любых весах и не доказательство спроса. Баллы учебные.")
        elif mode == "decision":
            decision = active("DEC-001")
            payload = decision["payload"]
            say("Реального принятого бизнес-решения НЕТ.")
            say(
                key({"entity_id": decision["id"], "revision": decision["revision"]})
                + ": "
                + payload["status"]
                + "; candidate="
                + key(payload["selected_option_ref"])
            )
            say("DEC закрепляет: " + ", ".join(key(r) for r in payload["strategy_refs"]))
            say(
                "Более новые предложения: "
                + ", ".join(f"{identity}@{active(identity)['revision']}" for identity in ("STR-001", "STR-002"))
            )
            say("Они не подменяют DEC. Внедрение до H запрещено; это НЕ победа status quo по баллам.")
            say("Следующее: человек выбирает направление, определение результата, допустимые данные и ресурсы.")
        elif mode == "economics":
            say("ЭКОНОМИКА — СХЕМА ПРОВЕРКИ, НЕ ИЗМЕРЕННАЯ ОКУПАЕМОСТЬ")
            say("Оставить: учитывать ручную работу, поддержку и ошибки; baseline не бесплатен.")
            say("Улучшить: выигрыш времени/качества минус изменение, поддержка и дополнительный шаг.")
            say("Сузить: отдельные объём случаев, затраты и эффект; не переносить числа из improve.")
            say("Закрыть: избегаемые расходы минус миграция, обязательства и потерянная полезность.")
            say(
                "N, ставка часа, delta времени, стоимость и диапазоны UNKNOWN. 30000/10000 — не экономика всех направлений."
            )
        elif mode == "communication":
            say("КОММУНИКАЦИЯ — НЕ РАССЫЛКА, А ЧЕРНОВИК ДЛЯ ПРОВЕРКИ ПОНИМАНИЯ")
            say("Гипотеза аудитории: составитель итогов и согласующий коллега. Барьер: лишний шаг и внешний upload.")
            say(
                "Пример: Предлагаем разобрать, где задержка: в проверке владельцев или ожидании согласования. Записи пока не присылайте."
            )
            say(
                "Пример: Проверяем гипотезу локальной проверки черновика. Ускорение и автоматическую отправку не обещаем."
            )
            say("Действие: согласовать допустимость разбора. Попросить пересказать ограничения своими словами.")
        elif mode == "memory":
            result = retrieve(store, "согласие", mode="lexical")["data"]
            say(
                "Реальный lexical retrieval: полный corpus в пределах128chunks, Unicode offsets; semantic_vectors_used=False."
            )
            for hit in result["hits"][:2]:
                say(key(hit["ref"]) + " chars=" + str((hit["start_char"], hit["end_char"])) + "; " + hit["text"][:170])
            say("English embeddings не доказывают русский semantic paraphrase. Запросы по словам — резервный lexical.")
        elif mode == "pause":
            saved = store.checkpoint(
                "V5 corrected arithmetic and explicit pending proposals demonstrated; real business H remains pending",
                store.status()["case_revision"],
            )
            say("Реальный checkpoint: revision " + str(saved["case_revision"]))
        elif mode == "resume":
            result = subprocess.run(
                [sys.executable, "-m", "tools.cli", "status", "--case", "test-core"],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(result.stdout)
            say("Новый процесс читает committed journal: revision=" + str(data["case_revision"]))
            say("awaiting_human=" + str(data["data"]["state"]["awaiting_human"]))
            say("Память чата не нужна; человек не подтверждён автоматически.")
        elif mode == "impact":
            result = impact(store, "CLM-002")["data"]
            say("Реальный dependency closure CLM-002: affected=" + str(len(result["affected"])))
            say("Это зарегистрированные связи, не доказательство спроса и не автоматический пересмотр STR.")
        elif mode == "limits":
            say("ПРОВЕРЕНО: арифметика, локальные контракты, полный lexical, сохранение/новый процесс.")
            say("НЕ ДОКАЗАНО: спрос/эффект, полная цена результата, русский semantic, listening STT, другая ОС.")
            say(
                "Нет новых платных вызовов, интервью или benchmark. Реальные URL и внешний видеохост требуют разрешения/доступа."
            )
            say("Предложения pending; юридическую отправку выполняет капитан. Исторические v3/v4 сохранены.")
        else:
            raise SystemExit("Unknown explicit demonstration mode")


if __name__ == "__main__":
    main()
