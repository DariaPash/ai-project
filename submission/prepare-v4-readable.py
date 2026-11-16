"""Local synthetic-only proposals from one verified Store snapshot; no mutation/network."""

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.contracts import digest, key, ref, references, sha
from tools.errors import CoreError
from tools.store import Store

TITLES = {
    "brief": "Бриф",
    "option": "Вариант решения",
    "strategy": "Стратегия",
    "research_plan": "План исследования",
    "promise": "Матрица обещаний",
    "experiment": "Проверочный эксперимент",
    "decision": "Предложение решения",
    "claim": "Утверждение",
    "question": "Открытый вопрос",
    "interview_analysis": "Анализ учебных интервью",
    "calculation": "Учебный расчёт",
    "obligation": "Обязательство",
}
LABELS = {
    "status_quo": "Сохранить текущий процесс",
    "improve": "Улучшить локальную проверку",
    "refocus": "Сменить задачу: проверять готовые списки",
    "close": "Закрыть направление",
    "privacy": "Приватность",
    "reversibility": "Обратимость",
    "value": "Ценность",
}
WIN_CONDITIONS = {
    "Waiting/coordination dominates review, or the proposed gain is below the predeclared useful threshold": "Ожидание/координация важнее проверки либо выигрыш ниже заранее предложенного полезного порога.",
    "A permitted comparison clears the proposed 10% useful reduction without losing accuracy or increasing privacy risk": "Разрешённое сравнение достигает предложенного снижения времени на 10% без потери точности или роста privacy risk.",
    "The narrower non-recording job is admissible and useful whereas both meeting-draft mechanisms are inadmissible or unnecessary": "Узкая задача без записей допустима и полезна, а оба варианта meeting drafts недопустимы или не нужны.",
    "No admissible bounded mechanism meets the useful/quality threshold and remaining support/migration costs are fundable": "Ни один допустимый ограниченный механизм не достигает порога пользы/качества, а оставшиеся поддержка и миграция обеспечены ресурсами.",
}
WARNING = (
    "**Локальное предложение v4, не согласованная бизнес-стратегия.** "
    "Источники учебные; модельные роли не реальные клиенты. Перевод и пояснения "
    "не изменяют Store, права, исторические approvals или awaiting_human. "
    "Исходные формулировки и точные refs сохранены отдельно.\n\n"
)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def block(value):
    text = value if isinstance(value, str) else dumps(value)
    fence = "```"
    while fence in text:
        fence += "`"
    return fence + "\n" + text + "\n" + fence + "\n\n"


def load_case(project, case_id):
    with Store(project, case_id) as store:
        with store.io.lock(store.lock_path):
            snapshot, warnings, _ = store._load()
            records = store.records(snapshot)
            sources = [r for r in records.values() if r["kind"] == "source"]
            if not case_id.startswith("test-") or snapshot["namespace"] != "test" or not sources:
                raise ValueError("Only explicit test-* synthetic cases with sources are supported")
            if any(
                r["payload"].get("origin") != "synthetic_fixture"
                or not r["payload"].get("rights", {}).get("processing")
                for r in sources
            ):
                raise ValueError("Non-synthetic or non-processable source")
            if any(
                not r.get("lineage_roots") or set(r["lineage_roots"]) - {"synthetic_fixture", "model_simulation"}
                for r in records.values()
                if r["kind"] in TITLES
            ):
                raise ValueError("Unknown or real business provenance")
            active = [records[f"{eid}@{rev}"] for eid, rev in sorted(snapshot["active"].items())]
            selected = {key(ref(r)): r for r in active if r["kind"] in TITLES}
            pending, seen = list(selected.values()), set(selected)
            while pending:
                for dependency in references(pending.pop()["payload"]):
                    identity = key(dependency)
                    if identity not in seen:
                        seen.add(identity)
                        parent = records[identity]
                        pending.append(parent)
                        if parent["kind"] in TITLES:
                            selected[identity] = parent
            return snapshot, records, active, dict(sorted(selected.items())), warnings


def located_items(value):
    if isinstance(value, dict):
        if isinstance(value.get("locator"), dict) and isinstance(value.get("ref"), dict):
            yield value
        for child in value.values():
            yield from located_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from located_items(child)


def citation(item, records):
    loc, reference = item["locator"], item["ref"]
    source = records[key(reference)]
    if source["kind"] != "source" or loc["source_revision"] != reference["revision"]:
        raise ValueError("Citation source revision mismatch")
    if source["payload"]["sha256"] != loc["source_hash"]:
        raise ValueError("Citation source hash mismatch")
    matches = [r for r in records.values() if r["id"] == loc["extraction_id"]]
    if len(matches) != 1:
        raise ValueError("Ambiguous or missing immutable extraction")
    extraction = matches[0]
    p = extraction["payload"]
    if p["source_ref"] != reference or p["source_hash"] != loc["source_hash"]:
        raise ValueError("Citation extraction source mismatch")
    quote = loc.get("exact_quote")
    if quote is not None and not any(
        f["kind"] == loc["kind"] and f["coordinates"] == loc["coordinates"] and quote in f["text"]
        for f in p["fragments"]
    ):
        raise ValueError("Quote does not match the exact located fragment")
    return (
        f"**{key(reference)} → {key(ref(extraction))}**; "
        f"SHA-256 исходных bytes `{loc['source_hash']}`; вид `{loc['kind']}`; координаты:\n"
        + block(loc["coordinates"])
        + (
            "Точная цитата (без перевода):\n" + block(quote)
            if quote is not None
            else "Точная цитата не сохранена; не восстановлена догадкой.\n\n"
        )
    )


def compare(options, records):
    text = "# Четыре механизма: оценки и чувствительность\n\n" + WARNING
    groups = {}
    for option in options:
        plan_ref = option["payload"].get("research_plan_ref")
        if plan_ref:
            groups.setdefault(key(plan_ref), []).append(option)
    for identity, group in sorted(groups.items()):
        criteria = records[identity]["payload"]["criteria"]
        text += f"## Критерии из {identity}\n\nШкала и исходные веса (не измеренные предпочтения):\n\n" + block(
            criteria
        )
        for index, weights in enumerate([criteria["weights"], *criteria.get("sensitivity_weights", [])]):
            text += f"### {'Базовые веса' if index == 0 else 'Чувствительность ' + str(index)}\n\n"
            text += "; ".join(f"{LABELS.get(k, k)}: {v}" for k, v in weights.items()) + ".\n\n"
            totals = []
            for option in group:
                scores = option["payload"].get("scores", {})
                if not all(k in scores for k in weights):
                    text += f"{key(ref(option))}: неполные оценки; итог неизвестен.\n\n"
                    continue
                total = sum((Decimal(str(weights[k])) * Decimal(str(scores[k])) for k in weights), Decimal(0))
                totals.append((key(ref(option)), total))
                text += f"- {key(ref(option))}, {LABELS.get(option['payload']['option_type'])}: **{total}**; оценки {dumps(scores)}\n"
            if totals:
                best = max(t for _, t in totals)
                text += "\nМаксимум при этих весах: " + ", ".join(k for k, t in totals if t == best) + ".\n\n"
        text += (
            "Сумма = Σ(вес × оценка). Это пересчёт сохранённых учебных суждений, "
            "не вероятность успеха. Смена весов может изменить предпочтение; "
            "их нельзя подбирать под фаворита.\n\n"
        )
    return text


def prepare(project, out, case_id="test-core", catalog_path=None):
    project, out = Path(project).resolve(), Path(out).absolute()
    if os.path.lexists(out):
        raise ValueError("Output already exists; choose a new directory")
    resolved = out.resolve()
    if resolved == project or (project / "cases") == resolved or (project / "cases") in resolved.parents:
        raise ValueError("Output must not be the project or any case/Store directory")
    if project in resolved.parents and any(x in {"planning", "v3"} for x in resolved.relative_to(project).parts):
        raise ValueError("Do not write development history or immutable v3 assets")
    snapshot, records, active, selected, warnings = load_case(project, case_id)
    catalog_file = (
        Path(catalog_path) if catalog_path else Path(__file__).with_name("v4-content") / "russian-catalog.json"
    )
    catalog = json.loads(catalog_file.read_text(encoding="utf-8")) if catalog_file.exists() else {}
    files, translated, missing = {}, [], []
    for identity, r in selected.items():
        p, entry = r["payload"], catalog.get(identity, {})
        text = f"# {TITLES[r['kind']]}: {identity}\n\n" + WARNING
        text += f"SHA-256 payload `{digest(p)}`; происхождение: {', '.join(r['lineage_roots'])}.\n\n"
        if entry.get("payload_sha256") == digest(p):
            text += entry["russian_markdown"].rstrip() + "\n\n"
            if p.get("wins_when") in WIN_CONDITIONS:
                text += "**Когда вариант предпочтителен:** " + WIN_CONDITIONS[p["wins_when"]] + "\n\n"
            translated.append(identity)
        else:
            text += (
                "**Русский смысловой перевод этой точной ревизии ещё не подготовлен.** "
                "Ниже полный оригинал; это явный gap, не готовый русский результат.\n\n"
            )
            missing.append(identity)
        text += "## Точные связи и исходные поля\n\n" + block(p)
        for item in located_items(p):
            text += citation(item, records)
        files[f"{r['id']}-r{r['revision']}.md"] = text.encode()
    evidence = (
        "# Проверяемые основания и границы интерпретации\n\n"
        + WARNING
        + "Цитата доказывает наличие текста, не его истинность. Повтор одного root "
        "не независимый источник. Учебная частота не распространённость.\n\n"
    )
    seen = set()
    for identity, r in selected.items():
        for item in located_items(r["payload"]):
            fingerprint = digest(item)
            if fingerprint not in seen:
                seen.add(fingerprint)
                evidence += f"## Основание из {identity}\n\n" + citation(item, records)
    delta = "# Предлагаемая дельта возможностей (не бизнес-approval)\n\n" + WARNING
    delta += (
        "Исторические CLM-002/EXP могут описывать отказ Apple Speech. Более поздний "
        "whisper receipt не меняет их bytes и не означает проверку качества/consent. "
        "MCP read/import не автоматический продуктовый экспорт. Нужны новые "
        "proposed revisions и реальный H на точный bundle; этот генератор их не создаёт.\n\n"
    )
    for r in active:
        if r["kind"] == "extraction" and r["id"] in {"EXT-017", "EXT-020"}:
            p = r["payload"]
            if p.get("coverage", {}).get("media", {}).get("engine", {}).get("engine") == "whisper.cpp":
                delta += (
                    "Фактически выполнено локальное распознавание whisper.cpp; это не прежний "
                    "отказ Apple Speech. Числа/отрицания остаются uncertain, listening не выполнен; "
                    "диаризация, качество русского языка и права на реальные записи не подтверждены.\n\n"
                )
            delta += f"## Технический receipt {key(ref(r))}\n\n" + block(
                {
                    "source_ref": p["source_ref"],
                    "source_hash": p["source_hash"],
                    "extractor": p["extractor"],
                    "warnings": p["warnings"],
                }
            )
            for f in p["fragments"]:
                excerpt = citation(
                    {
                        "ref": p["source_ref"],
                        "locator": {
                            "source_revision": p["source_ref"]["revision"],
                            "source_hash": p["source_hash"],
                            "extraction_id": r["id"],
                            "kind": f["kind"],
                            "coordinates": f["coordinates"],
                            "exact_quote": f["text"],
                        },
                    },
                    records,
                )
                evidence += excerpt
                delta += excerpt
    files["capability-delta-proposed.md"] = delta.encode()
    files["evidence.md"] = evidence.encode()
    files["options-comparison.md"] = compare([r for r in active if r["kind"] == "option"], records).encode()
    files["known-unknowns.md"] = (
        "# Известное и неизвестное\n\n"
        + WARNING
        + "Реальные клиенты, согласие на интервью/записи, владелец исполнения, baseline, "
        "эффект, бюджет внедрения и коммерческий спрос не установлены этим пакетом. "
        "CAL — вымышленные входы для проверки формулы, не прогноз продукта. "
        "Полная приёмка, benchmark и работа на другой ОС не подтверждены.\n\n"
        + "Runtime snapshot:\n"
        + block(snapshot["runtime"])
        + "Предупреждения Store:\n"
        + block(warnings)
    ).encode()
    index = "# Читаемый учебный кейс v4\n\n" + WARNING
    index += (
        f"Case `{case_id}`; committed revision {snapshot['case_revision']}; snapshot digest `{digest(snapshot)}`.\n\n"
    )
    index += (
        "Порядок: options-comparison.md → STR из точных DEC refs → PRM → EXP → evidence.md. "
        "Новая активная STR не заменяет автоматически pinned STR решения.\n\n"
    )
    for r in active:
        if r["kind"] == "decision":
            index += f"Точные refs решения {key(ref(r))}:\n" + block(r["payload"])
    index += "## Файлы\n\n" + "".join(f"- [{name}]({name})\n" for name in sorted(files))
    index += "\nРусский перевод отсутствует для: " + (", ".join(missing) or "нет пропусков") + ".\n"
    files["README.md"] = index.encode()
    manifest = {
        "format": "v4-readable-proposal-1",
        "case_id": case_id,
        "case_revision": snapshot["case_revision"],
        "snapshot_digest": digest(snapshot),
        "store_mutated": False,
        "publication_authorized": False,
        "business_approval_inferred": False,
        "translated_exact_records": translated,
        "translation_gaps": missing,
        "records": {
            identity: {
                "ref": ref(r),
                "record_sha256": snapshot["records"][identity]["sha256"],
                "payload_sha256": digest(r["payload"]),
            }
            for identity, r in selected.items()
        },
        "files": {name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in sorted(files.items())},
        "warnings": warnings,
    }
    out.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        with (out / name).open("xb") as stream:
            stream.write(raw)
    with (out / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(dumps(manifest) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Читаемые предложения из verified synthetic Store; без сети/мутаций")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", help="Явный корень Store с cases/")
    source.add_argument("--local-case-location", type=Path, help="Явный JSON-указатель собственного учебного кейса")
    parser.add_argument("--case", default="test-core")
    parser.add_argument("--out", required=True, type=Path, help="Новая локальная папка; без перезаписи")
    parser.add_argument("--catalog", type=Path, help="Exact-revision Russian catalog; hashes checked per entry")
    args = parser.parse_args()
    try:
        project, case_id = args.project, args.case
        if args.local_case_location:
            location = json.loads(args.local_case_location.read_text(encoding="utf-8"))
            relative = Path(location["project_relative_path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Pointer must be project-relative, without traversal")
            project = (ROOT / relative).resolve()
            if ROOT not in project.parents:
                raise ValueError("Pointer must stay inside the current project")
            case_id = location["case_id"]
        result = prepare(project, args.out, case_id, catalog_path=args.catalog)
        print(
            dumps(
                {
                    "ok": True,
                    "case_revision": result["case_revision"],
                    "snapshot_digest": result["snapshot_digest"],
                    "translation_gaps": result["translation_gaps"],
                }
            )
        )
    except (CoreError, OSError, ValueError, KeyError, TypeError) as error:
        print(
            dumps(
                {
                    "ok": False,
                    "code": getattr(error, "code", "PREPARATION_FAILED"),
                    "reason": "Проверка или запись не завершена; исходный Store не изменён. "
                    "Проверьте вход, права, целостность и новую папку назначения.",
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
