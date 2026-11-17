"""A genuine local demo driver: observe a new host-agent result, then commit proposals.

No model calls, fake outputs or automatic business decisions inside this script.
Run from the explicitly restored synthetic project, with its demo/ packet.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.contracts import key, sha
from tools.safeio import SafeRoot, canonical
from tools.store import Store
from tools.research_contracts import strategy_manifest
from tools.option_scoring import scenario


def say(text):
    print(textwrap.fill(str(text), width=103), flush=True)


def main():
    mode = sys.argv[1]
    project = Path.cwd()
    packet = json.loads((project / "demo/packet.json").read_text())
    if mode == "agent":
        if not (project / "demo/ready.fifo").exists():
            raise SystemExit(
                "Fresh host-agent handoff required; no model call or replay implied. Watch cli-demo.mp4 for the recorded run."
            )
        say("НОВЫЙ КОНТЕКСТ АГЕНТА: отдельный host task, не воспроизведение старой стратегии.")
        say("Синтетический packet SHA-256: " + sha(canonical(packet)))
        say("Ожидаем настоящий результат через локальный канал. Ожидание не ускоряется.")
        with (project / "demo/ready.fifo").open() as channel:
            message = channel.read(128)
        if message.strip() != "ready":
            raise SystemExit("Unexpected handoff; preserve recording")
        result = json.loads((project / "demo/agent-result.json").read_text())
        if (
            result["case_id"] != "test-core"
            or result["input_sha256"] != sha(canonical(packet))
            or result["business_H_confirmed"] is not False
        ):
            raise SystemExit("Result binding invalid")
        say("Получен новый ответ. Следующие вопросы действительно могут изменить выбор:")
        for q in result["questions"]:
            say("- " + q)
        say("Рекомендация: " + result["recommendation"])
        say("Это новая модельная гипотеза, НЕ согласие человека и НЕ доказанный спрос.")
        return
    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        active = lambda identity: records[f"{identity}@{snapshot['active'][identity]}"]
        if mode == "request":
            say("УЧЕБНЫЙ КЕЙС: «Как снизить ошибки и задержки при передаче итогов встреч?»")
            say("Начинаем с реальной сохранённой истории; новый контекст создаст новое предложение.")
            say("Все источники synthetic_fixture. Эффект, спрос и согласие бизнеса неизвестны.")
            say("Journal revision: " + str(snapshot["case_revision"]))
        elif mode == "sources":
            for identity in ("EXT-001", "EXT-002", "EXT-004"):
                record = active(identity)
                p = record["payload"]
                say(identity + "@" + str(record["revision"]) + " → " + str(p["source_ref"]))
                say("source SHA-256: " + p["source_hash"])
                say(p["text"][:440])
            say("Конфликт CLM-001@1: создание встречи/24ч ≠ экспорт/7д; определения нельзя смешивать.")
        elif mode == "options":
            options = [active(identity) for identity in ("OPT-001", "OPT-002", "OPT-003", "OPT-004")]
            for identity in ("OPT-001", "OPT-002", "OPT-003", "OPT-004"):
                p = active(identity)["payload"]
                say(identity + ": " + p["option_type"] + " / scores=" + str(p["scores"]))
            plan = records[key(options[0]["payload"]["research_plan_ref"])]
            criteria = plan["payload"]["criteria"]
            for weights in [criteria["weights"], *criteria.get("sensitivity_weights", [])]:
                totals, leaders = scenario(options, weights)
                say("Учебные веса " + str(weights) + ": " + "; ".join(k + "=" + str(v) for k, v in totals.items()))
                say("Лидер только при этих весах: " + ", ".join(leaders))
            say("Показанные сценарии не доказывают спрос, устойчивость при любых весах или бизнес-выбор.")
        elif mode == "commit":
            result = json.loads((project / "demo/agent-result.json").read_text())
            if result["input_sha256"] != sha(canonical(packet)) or result["business_H_confirmed"] is not False:
                raise SystemExit("Unbound or falsely approved result")
            if active("STR-001")["revision"] != packet["strategy_baseline"]["STR-001"]:
                raise SystemExit("Proposal already saved or baseline changed; reconcile, do not repeat")
            for identity, kind in (("STR-001", "product"), ("STR-002", "communication")):
                old = active(identity)["payload"]
                sections = result["strategies"][kind]
                text = "# Новое предложение отдельного контекста / синтетика / H pending\n\n"
                text += "\n\n".join("## " + name + "\n" + content for name, content in sections.items()) + "\n"
                parents = [old["selected_option_ref"], old["option_choice_ref"], *old["basis_refs"]]

                def artifact(raw, media):
                    return store.record(
                        "artifact",
                        {
                            "payload": {
                                "sha256": sha(raw),
                                "size": len(raw),
                                "media_type": media,
                                "origin": "model_simulation",
                                "parent_refs": parents,
                                "processing_kind": "LLM-assisted",
                            }
                        },
                        store.status()["case_revision"],
                        artifacts={sha(raw): raw},
                    )["data"]["ref"]

                payload = {**old, "sections": sections, "text": text, "content_sha256": sha(text.encode())}
                payload["artifact_ref"] = artifact(text.encode(), "text/markdown")
                payload["manifest_ref"] = artifact(canonical(strategy_manifest(payload)), "application/json")
                saved = store.record("strategy", {"id": identity, "payload": payload}, store.status()["case_revision"])
                say("Сохранено через Store: " + str(saved["data"]["ref"]))
            say("Предыдущие STR и DEC неизменны. Новое предложение не перепривязывает бизнес-решение.")
        elif mode in ("product", "communication"):
            record = active("STR-001" if mode == "product" else "STR-002")
            say(record["id"] + "@" + str(record["revision"]) + " / НОВОЕ ПРЕДЛОЖЕНИЕ / H pending")
            for name, content in record["payload"]["sections"].items():
                say(name + ": " + content)
        elif mode == "experiment":
            p = active("EXP-001")["payload"]
            say("EXP-001@" + str(active("EXP-001")["revision"]) + ": baseline = null, не ноль.")
            say("14 дней и порог 10% — предложенный учебный протокол, не измеренный результат.")
            say("При отсутствии consent/baseline, нарушении privacy/точности или лимита — STOP.")
            say("Сравнительный benchmark запрещён. DEC остаётся pending; owner unassigned.")
        elif mode == "pause":
            r = store.checkpoint(
                "Live demo proposals saved; resume via new process; business reconsideration pending.",
                snapshot["case_revision"],
            )
            say("Действительный checkpoint: revision " + str(r["case_revision"]))
        elif mode == "resume":
            r = subprocess.run(
                [sys.executable, "-m", "tools.cli", "status", "--case", "test-core"],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(r.stdout)
            say("НОВЫЙ ПРОЦЕСС читает committed journal, а не память старого чата.")
            say("revision=" + str(data["case_revision"]) + "; stage=" + data["data"]["state"]["stage"])
            say("awaiting_human=" + str(data["data"]["state"]["awaiting_human"]))
            say("Следующий шаг: получить ответ реального пользователя на пересмотр, не додумывать согласие.")
        elif mode == "impact":
            from tools.graph import impact

            r = impact(store, "CLM-002")
            say("Реальный обход impact CLM-002; затронутых узлов: " + str(len(r["data"]["affected"])))
            say("Новая техническая возможность STT не доказывает точность или спрос; источник влияет на обе стратегии.")
            say("Нерелевантный комментарий не является основанием молча изменить pinned DEC.")
        elif mode == "integrations":
            say("ИСТОРИЧЕСКИЕ ТРАССЫ, НЕ ПОВТОРНЫЕ ВЫЗОВЫ:")
            say("EXT-017@1: whisper.cpp выполнен локально; числа/отрицания не проверены прослушиванием.")
            say("EXT-020@1: filesystem MCP read/import; не автоматический экспорт продукта.")
            say("Другой клиент Codex запускался на том же Mac; one-use grant повторно не использован.")
            say("77 targeted tests + clean restore уже сохранены; общий итог регрессии отдельно в manifest.")
        else:
            raise SystemExit("Unknown explicit demo action")


if __name__ == "__main__":
    main()
