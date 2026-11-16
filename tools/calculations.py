"""Explicit, reproducible metrics. No eval, generated code or causal inference."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_EVEN, localcontext
import csv
from io import StringIO
import re
from importlib.resources import files

from .contracts import digest, key, ref, sha, validate_schema
from .errors import CoreError
from .records import RecordBatch
from .safeio import canonical, parse_json

METHOD_VERSION = "step02-metrics-v1"


def ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def csv_safe(value):
    if isinstance(value, str) and (
        value.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        or value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


def result_csv(result, roots):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["metric", "value", "origin_roots"])

    def visit(value, path):
        if isinstance(value, dict):
            for k, v in value.items():
                visit(v, path + [str(k)])
        elif isinstance(value, list):
            for i, v in enumerate(value):
                visit(v, path + [str(i)])
        else:
            writer.writerow([csv_safe(".".join(path)), csv_safe(value), "|".join(roots)])

    visit(result, [])
    return stream.getvalue().encode()


def _date(value, date_format):
    if not isinstance(value, str) or not value:
        raise CoreError("DATE_MISSING", "Date is missing; no implicit imputation")
    if date_format not in {"%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"}:
        raise CoreError("DATE_FORMAT", "Use an explicit supported ISO date format; ambiguous dates are not guessed")
    try:
        return datetime.strptime(value, date_format).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CoreError("DATE_INVALID", "Date does not match its explicit format") from exc


def _rows(table, fields, required, definitions):
    columns = table["columns"]
    if any(name not in fields or fields[name] not in columns for name in required):
        raise CoreError("FIELD_MAP", "Required fields are absent from the explicit table mapping")
    rows = []
    for row in table["rows"]:
        mapped = {name: row["values"][fields[name]] for name in required}
        for name in required:
            formula = row.get("formula_cells", {}).get(fields[name])
            if formula and (
                formula["cache_missing"]
                or definitions.get("formula_cache_policy", "reject") != "allow_cached_with_warning"
            ):
                raise CoreError(
                    "FORMULA_CACHE", "Numeric/date source has unverified or missing formula cache; no recalculation", 3
                )
        rows.append(mapped)
    return rows


def retention_data(tables, spec):
    d = spec["definitions"]
    fields = spec["fields"]
    required = {
        "timezone",
        "date_format",
        "as_of",
        "retention_day",
        "retention_window",
        "dedup",
        "missing_id",
        "missing_segment",
    }
    if (
        not required.issubset(d)
        or d["timezone"] != "UTC"
        or d["retention_window"] != "complete_calendar_day"
        or d["dedup"] != "exact"
        or d["missing_id"] != "exclude"
        or d["missing_segment"] != "unknown"
    ):
        raise CoreError(
            "METRIC_DEFINITION", "Define UTC, complete calendar-day window, exact dedup and explicit missing policies"
        )
    if type(d["retention_day"]) is not int or not 1 <= d["retention_day"] <= 365:
        raise CoreError("RETENTION_DAY", "Retention day must be an integer between 1 and 365")
    try:
        as_of = datetime.fromisoformat(d["as_of"].replace("Z", "+00:00"))
        if as_of.tzinfo is None:
            raise ValueError()
        as_of = as_of.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CoreError("AS_OF", "Observation cutoff needs an explicit timezone") from exc
    if "registrations" not in tables or "d7" not in tables:
        raise CoreError("INPUT_TABLES", "Cohort metrics need registrations and d7 tables")
    quality = {
        "registration_duplicates": 0,
        "registration_missing_ids": 0,
        "event_duplicates": {},
        "event_missing_ids": {},
        "unmatched_event_ids": {},
        "events_after_cutoff": {},
        "immature_excluded": 0,
    }
    users = {}
    for row in _rows(tables["registrations"], fields, ["user_id", "signup_at", "segment"], d):
        user = row["user_id"]
        if user is None or str(user).strip() == "":
            quality["registration_missing_ids"] += 1
            continue
        if not isinstance(user, str) or user != user.strip():
            raise CoreError("USER_ID", "User IDs must be explicit non-whitespace strings")
        signup = _date(row["signup_at"], d["date_format"])
        if signup >= as_of:
            raise CoreError("SIGNUP_FUTURE", "Registration is outside the observation period")
        segment = row["segment"] if row["segment"] not in (None, "") else "unknown"
        if not isinstance(segment, str):
            raise CoreError("SEGMENT_TYPE", "Segment categories must be explicit strings, not silently coerced")
        normalized = {"signup": signup, "segment": segment, "cohort": signup.date().isoformat()}
        if user in users:
            if users[user] != normalized:
                raise CoreError("DUPLICATE_CONFLICT", "Duplicate user has conflicting registration data")
            quality["registration_duplicates"] += 1
            continue
        users[user] = normalized
    for data in users.values():
        day = data["signup"].replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=d["retention_day"])
        data.update(window_start=day, window_end=day + timedelta(days=1), mature=as_of >= day + timedelta(days=1))
    quality["immature_excluded"] = sum(not u["mature"] for u in users.values())
    events = {}
    for name in ("d7", "activations"):
        if name not in tables:
            continue
        seen = set()
        result = {}
        duplicate = missing = unmatched = future = 0
        for row in _rows(tables[name], fields, ["user_id", "event_at"], d):
            user = row["user_id"]
            if user is None or str(user).strip() == "":
                missing += 1
                continue
            if not isinstance(user, str) or user != user.strip():
                raise CoreError("USER_ID", "Event user ID is invalid")
            at = _date(row["event_at"], d["date_format"])
            signature = (user, at)
            if signature in seen:
                duplicate += 1
                continue
            seen.add(signature)
            if user not in users:
                unmatched += 1
                continue
            if at < users[user]["signup"]:
                raise CoreError("EVENT_BEFORE_SIGNUP", "Event precedes the registration")
            if at >= as_of:
                future += 1
                continue
            result.setdefault(user, []).append(at)
        events[name] = result
        quality["event_duplicates"][name] = duplicate
        quality["event_missing_ids"][name] = missing
        quality["unmatched_event_ids"][name] = unmatched
        quality["events_after_cutoff"][name] = future
    active = {
        user
        for user, data in users.items()
        if data["mature"] and any(data["window_start"] <= at < data["window_end"] for at in events["d7"].get(user, []))
    }
    return users, events, active, quality


def cohort_metrics(tables, spec):
    users, events, active, quality = retention_data(tables, spec)
    parameters = spec["parameters"]
    allowed = {"cohort", "allow_historical"}
    if set(parameters) - allowed:
        raise CoreError("PARAMETERS", "Unknown cohort/funnel parameter")
    selected = {
        user
        for user, data in users.items()
        if data["mature"] and (not parameters.get("cohort") or data["cohort"] == parameters["cohort"])
    }
    if spec["operation"] == "funnel":
        if "activations" not in events:
            raise CoreError("FUNNEL_INPUT", "Funnel needs the activation events table")
        window = spec["definitions"].get("activation_window_days")
        if type(window) is not int or not 1 <= window <= spec["definitions"]["retention_day"]:
            raise CoreError("ACTIVATION_WINDOW", "Funnel requires an explicit bounded activation window in days")
        activation_events = {
            user: [
                at for at in events["activations"].get(user, []) if at < users[user]["signup"] + timedelta(days=window)
            ]
            for user in selected
        }
        activated = {user for user in selected if activation_events[user]}
        retained = {
            user
            for user in activated & active
            if any(
                a <= r and users[user]["window_start"] <= r < users[user]["window_end"]
                for a in activation_events[user]
                for r in events["d7"].get(user, [])
            )
        }
        result = {
            "mature_registrations": len(selected),
            "activated": len(activated),
            "d7_after_activation": len(retained),
            "activation": ratio(len(activated), len(selected)),
            "conditional_d7": ratio(len(retained), len(activated)),
        }
    else:
        by_cohort = {}
        for cohort in sorted({u["cohort"] for u in users.values()}):
            population = {user for user in selected if users[user]["cohort"] == cohort}
            by_cohort[cohort] = {
                **ratio(len(population & active), len(population)),
                "immature_excluded": sum(data["cohort"] == cohort and not data["mature"] for data in users.values()),
            }
        by_segment = {}
        for segment in sorted({str(u["segment"]) for u in users.values()}):
            population = {user for user in selected if str(users[user]["segment"]) == segment}
            by_segment[segment] = ratio(len(population & active), len(population))
        result = {
            "unique_registrations": len(users),
            "mature": len(selected),
            "d7_active": len(selected & active),
            "retention": ratio(len(selected & active), len(selected)),
            "by_cohort": by_cohort,
            "by_segment": by_segment,
        }
    result["data_quality"] = quality
    result["limitations"] = [
        "Synthetic origin is inherited separately; these observations do not prove demand or causality",
        "Missing/duplicates/immaturity follow the explicit spec; no statistical-power claim",
    ]
    if spec["definitions"].get("formula_cache_policy") == "allow_cached_with_warning":
        result["limitations"].append("Formula cache freshness was accepted explicitly and is not verified by this tool")
    return result


def _decimal(value):
    if isinstance(value, bool) or not re.fullmatch(r"-?\d{1,15}(\.\d{1,6})?", str(value)):
        raise CoreError("NUMBER", "Use bounded finite decimal values, not expressions or ambiguous numbers")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise CoreError("NUMBER", "Invalid decimal") from exc


def money(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def economy_base(tables, spec):
    if "economics" not in tables:
        raise CoreError("ECONOMY_INPUT", "Economic calculations require the economics input table")
    definitions = spec["definitions"]
    if not re.fullmatch(r"[A-Z]{3}", definitions.get("currency", "")) or definitions.get("period") != "month":
        raise CoreError("ECONOMY_UNITS", "Declare a single currency and monthly period")
    rows = _rows(tables["economics"], spec["fields"], ["name", "value", "currency", "period"], definitions)
    parameters = {}
    allowed = {"payers", "price", "variable_cost", "fixed_cost", "investment", "incremental_net"}
    for row in rows:
        name = row["name"]
        if name not in allowed or name in parameters:
            raise CoreError("ECONOMY_PARAMETER", "Unknown/duplicate economic parameter")
        if row["currency"] != definitions["currency"] or row["period"] != (
            "one_time" if name == "investment" else "month"
        ):
            raise CoreError(
                "ECONOMY_UNITS", "Mixed currency/period requires an explicit conversion, not silent summation"
            )
        parameters[name] = _decimal(row["value"])
    if set(parameters) != allowed:
        raise CoreError("ECONOMY_MISSING", "Required economic parameter is absent")
    return parameters


def evaluate_economy(base, overrides, currency):
    if not isinstance(overrides, dict):
        raise CoreError("ECONOMY_OVERRIDE", "Economic overrides must be an explicit object")
    with localcontext() as context:
        context.prec = 64
        return _evaluate_economy(base, overrides, currency)


def _evaluate_economy(base, overrides, currency):
    if set(overrides) - set(base):
        raise CoreError("ECONOMY_OVERRIDE", "Unknown economic override")
    p = {**base, **{name: _decimal(value) for name, value in overrides.items()}}
    if (
        any(value < 0 for name, value in p.items() if name != "incremental_net")
        or p["payers"] != p["payers"].to_integral_value()
    ):
        raise CoreError("ECONOMY_RANGE", "Counts must be nonnegative integers and costs/prices nonnegative")
    revenue = p["payers"] * p["price"]
    margin = p["price"] - p["variable_cost"]
    contribution = p["payers"] * margin
    net = contribution - p["fixed_cost"]
    return {
        "currency": currency,
        "period": "month",
        "parameters": {name: str(value) for name, value in p.items()},
        "revenue": money(revenue),
        "contribution": money(contribution),
        "net": money(net),
        "break_even_customers": int((p["fixed_cost"] / margin).to_integral_value(rounding=ROUND_CEILING))
        if margin > 0
        else None,
        "payback_months": money(p["investment"] / p["incremental_net"]) if p["incremental_net"] > 0 else None,
        "limitations": [
            "Scenario assumptions, not a validated forecast",
            "Break-even undefined at nonpositive contribution; simple payback ignores discounting and changes in cash flow",
        ],
    }


def compute(tables, spec):
    result = _compute(tables, spec)
    if (
        spec["operation"] in {"economics", "scenarios", "sensitivity"}
        and spec["definitions"].get("formula_cache_policy") == "allow_cached_with_warning"
    ):
        result.setdefault("limitations", []).append(
            "Formula cache freshness was explicitly accepted, not verified or recalculated"
        )
    return result


def _compute(tables, spec):
    validate_schema("metrics-spec", spec)
    if "allow_historical" in spec["parameters"] and type(spec["parameters"]["allow_historical"]) is not bool:
        raise CoreError("PARAMETERS", "allow_historical must be an explicit boolean")
    operation = spec["operation"]
    if operation in {"cohorts", "segments", "funnel"}:
        return cohort_metrics(tables, spec)
    base = economy_base(tables, spec)
    params = spec["parameters"]
    currency = spec["definitions"]["currency"]
    if operation == "economics":
        if set(params) - {"overrides", "allow_historical"}:
            raise CoreError("PARAMETERS", "Unknown economy parameter")
        return evaluate_economy(base, params.get("overrides", {}), currency)
    if operation == "scenarios":
        if set(params) - {"scenarios", "allow_historical"}:
            raise CoreError("PARAMETERS", "Unknown scenario parameter")
        scenarios = params.get("scenarios")
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 100:
            raise CoreError("SCENARIOS_LIMIT", "Define one to 100 explicit scenarios")
        if any(
            not isinstance(s, dict) or set(s) != {"name", "overrides"} or not isinstance(s["name"], str)
            for s in scenarios
        ) or len({s["name"] for s in scenarios}) != len(scenarios):
            raise CoreError("SCENARIO_NAMES", "Scenario names must be explicit and unique")
        return {
            "scenarios": [{"name": s["name"], **evaluate_economy(base, s["overrides"], currency)} for s in scenarios]
        }
    if operation == "sensitivity":
        if set(params) - {"parameter", "values", "allow_historical"}:
            raise CoreError("PARAMETERS", "Unknown sensitivity parameter")
        name, values = params.get("parameter"), params.get("values")
        if name not in base or not isinstance(values, list) or not 1 <= len(values) <= 100:
            raise CoreError("SENSITIVITY_LIMIT", "Define a valid parameter and one to 100 values")
        return {
            "parameter": name,
            "cases": [{"value": str(value), **evaluate_economy(base, {name: value}, currency)} for value in values],
        }
    raise CoreError("OPERATION", "Unsupported operation")


def metrics(store, spec, expected):
    validate_schema("metrics-spec", spec)
    method_version = METHOD_VERSION + ":" + sha(files("tools").joinpath("calculations.py").read_bytes())

    def usable(snapshot, _data=None):
        records = store.records(snapshot)
        for item in spec["inputs"].values():
            sr = item["source_ref"]
            if sr["case_id"] != store.case_id or key(sr) not in records:
                raise CoreError("INPUT_REF", "Metric source is missing or cross-case")
            source = records[key(sr)]
            if source["kind"] != "source":
                raise CoreError("INPUT_REF", "Metric source ref has the wrong kind")
            current = records[f"{sr['entity_id']}@{snapshot['active'][sr['entity_id']]}"]
            if current["payload"]["status"] != "available" or not current["payload"]["rights"]["processing"]:
                raise CoreError(
                    "INPUT_STALE", "Current source status/rights forbid using even a historical revision", 3
                )
            if (
                source["payload"]["status"] != "available"
                or not source["payload"]["rights"]["processing"]
                or (
                    snapshot["active"].get(sr["entity_id"]) != sr["revision"]
                    and not spec["parameters"].get("allow_historical", False)
                )
            ):
                raise CoreError("INPUT_STALE", "Metric source is unavailable, forbidden or historical", 3)
        return True

    def builder(snapshot):
        usable(snapshot)
        batch = RecordBatch(store, snapshot)
        tables = {}
        manifest = {}
        input_refs = []
        for name, item in spec["inputs"].items():
            sr, er = item["source_ref"], item["extraction_ref"]
            if (
                sr["case_id"] != store.case_id
                or er["case_id"] != store.case_id
                or key(sr) not in batch.records
                or key(er) not in batch.records
            ):
                raise CoreError("INPUT_REF", "Metric input references are absent or cross a case boundary")
            source, extraction = batch.records[key(sr)], batch.records[key(er)]
            if (
                source["kind"] != "source"
                or extraction["kind"] != "extraction"
                or extraction["payload"]["source_ref"] != sr
                or source["payload"]["sha256"] != item["source_sha256"]
            ):
                raise CoreError("INPUT_HASH", "Metric input references/hash do not match")
            if source["payload"]["status"] != "available" or (
                snapshot["active"].get(sr["entity_id"]) != sr["revision"]
                and not spec["parameters"].get("allow_historical", False)
            ):
                raise CoreError(
                    "INPUT_STALE", "Metric input is unavailable or historical; no silent use of old data", 3
                )
            table_ref = extraction["payload"].get("tables_ref")
            if table_ref is None:
                raise CoreError("INPUT_TABLE", "Extraction has no tabular data")
            table_record = batch.records[key(table_ref)]
            bundle = parse_json(store.blob(table_record["payload"]["sha256"]))
            if item["sheet"] not in bundle["tables"]:
                raise CoreError("INPUT_SHEET", "Requested table/sheet is absent")
            tables[name] = bundle["tables"][item["sheet"]]
            manifest[name] = {
                **item,
                "table_artifact_ref": table_ref,
                "table_sha256": table_record["payload"]["sha256"],
                "row_count": len(tables[name]["rows"]),
                "selection": {
                    "kind": "entire_imported_table",
                    "header_coordinates": tables[name]["header_coordinates"],
                    "first_row_coordinates": tables[name]["rows"][0]["coordinates"] if tables[name]["rows"] else None,
                    "last_row_coordinates": tables[name]["rows"][-1]["coordinates"] if tables[name]["rows"] else None,
                },
            }
            for reference in (sr, er, table_ref):
                if reference not in input_refs:
                    input_refs.append(reference)
        result = compute(tables, spec)
        roots = sorted(
            {origin for reference in input_refs for origin in batch.records[key(reference)]["lineage_roots"]}
        )
        origin = roots[0]
        spec_ref = batch.artifact(canonical(spec), "application/json", origin, input_refs)
        result_ref = batch.artifact(
            canonical(
                {"result": result, "origin_roots": roots, "input_manifest": manifest, "method_version": method_version}
            ),
            "application/json",
            origin,
            input_refs,
        )
        csv_ref = batch.artifact(result_csv(result, roots), "text/csv", origin, input_refs)
        calculation = batch.add(
            "calculation",
            {
                "operation": spec["operation"],
                "formula": "D7 = unique target-day active users / mature registrations; activation = eligible activation users / mature registrations; conditional D7 = ordered retained activation users / activation users; revenue=payers*price; contribution=payers*(price-variable_cost); net=contribution-fixed_cost; break_even=ceil(fixed_cost/(price-variable_cost)); simple_payback=investment/incremental_net. Scenario/sensitivity grids repeat these formulas with their explicit overrides.",
                "input_refs": input_refs,
                "parameters": {"definitions": spec["definitions"], **spec["parameters"]},
                "result": result,
                "limitations": [
                    "Not causal inference or evidence of real demand from synthetic inputs",
                    "All input refs/hashes/parameters are pinned",
                ],
                "spec_ref": spec_ref,
                "output_refs": [result_ref, csv_ref],
                "input_manifest": manifest,
                "method_version": method_version,
            },
        )
        return batch.finish(
            {
                "calculation_ref": calculation,
                "result": result,
                "origin_roots": roots,
                "result_artifact_ref": result_ref,
                "csv_artifact_ref": csv_ref,
            }
        )

    return store._mutate(
        "metrics", {"spec": spec, "method_version": method_version}, expected, builder, reuse_if=usable
    )
