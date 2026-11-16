"""Safe snapshots, bounded parsers and located source/extraction records."""

import base64
import csv
from datetime import date, datetime
import importlib.metadata
from io import BytesIO, StringIO
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import PurePosixPath
from importlib.resources import files
import zipfile

from .contracts import digest, key, ref, sha, validate_schema
from .errors import CoreError
from .records import RecordBatch
from .safeio import canonical, parse_json, parts
from .store import now

PARSER_VERSION = "step02-parser-v1"
MIME = {
    "md": "text/markdown",
    "txt": "text/plain",
    "pdf_text": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html_snapshot": "text/html",
    "image": "image/png",
    "scan_pdf": "application/pdf",
    "audio": "audio/wav",
    "video": "video/mp4",
}


def parser_profile(format_name):
    if format_name in {"image", "scan_pdf", "audio", "video"}:
        from .media import profile

        return profile(format_name)
    package = {"pdf_text": "pypdf", "xlsx": "openpyxl", "html_snapshot": "beautifulsoup4"}.get(format_name)
    try:
        version = importlib.metadata.version(package) if package else "stdlib-" + sys.version.split()[0]
    except importlib.metadata.PackageNotFoundError as exc:
        raise CoreError("PARSER_UNAVAILABLE", "Required format parser is not installed", 3) from exc
    return {
        "implementation": PARSER_VERSION,
        "engine": package or "stdlib",
        "engine_version": version,
        "python_version": sys.version.split()[0],
        "implementation_sha256": digest(
            {name: sha(files("tools").joinpath(name).read_bytes()) for name in ("sources.py", "parse_worker.py")}
        ),
    }


def allowed_input(store, filename):
    components = parts(filename)
    policy = store.io.json("config/source_policy.json")
    if policy.get("schema_version") != 1:
        raise CoreError("SOURCE_POLICY_VERSION", "Unknown source policy version")
    allowed = [parts(value.replace("<current-case>", store.case_id)) for value in policy["input_roots"]]
    if not any(
        tuple(components[: len(prefix)]) == tuple(prefix) and len(components) > len(prefix) for prefix in allowed
    ):
        raise CoreError("INPUT_ROOT", "Input is outside the explicitly allowed roots", 4)
    return "/".join(components), policy


def zip_preflight(raw, limits):
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
        entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise CoreError("XLSX_CORRUPT", "Input is not a valid XLSX archive") from exc
    with archive:
        if len(entries) > limits["max_zip_entries"]:
            raise CoreError("ZIP_LIMIT", "Archive entry count exceeds limits", 4)
        names, total = set(), 0
        for info in entries:
            name = info.filename
            member = PurePosixPath(name)
            if (
                name in names
                or member.is_absolute()
                or ".." in member.parts
                or any(ch in name for ch in ("\\", "\x00", ":"))
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.flag_bits & 1
            ):
                raise CoreError("ZIP_UNSAFE", "Archive has duplicate, encrypted, symlink or unsafe paths", 4)
            names.add(name)
            total += info.file_size
            if (
                total > limits["max_uncompressed_bytes"]
                or info.file_size / max(info.compress_size, 1) > limits["max_compression_ratio"]
            ):
                raise CoreError("ZIP_LIMIT", "Archive expansion exceeds limits", 4)
            if "vbaproject" in name.lower() or "externallinks/" in name.lower():
                raise CoreError("XLSX_EXTERNAL", "Macros and external workbook links are unsupported", 4)
        # Validate every directory entry before reading even one member.
        for info in entries:
            name = info.filename
            if name.endswith((".xml", ".rels")):
                content = archive.read(info)
                if b"\x00" in content or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                    raise CoreError("XML_ENTITY", "External/entity declarations are not allowed", 4)
                if name.endswith(".rels") and re.search(rb"TargetMode\s*=\s*['\"]External['\"]", content, re.I):
                    raise CoreError("XLSX_EXTERNAL", "External relationships are not followed", 4)


def _headers(values, limits, expected):
    if (
        not values
        or len(values) > limits["max_columns"]
        or any(not isinstance(v, str) or not v.strip() for v in values)
        or len(set(values)) != len(values)
    ):
        raise CoreError("TABLE_HEADERS", "Table requires bounded, nonempty, unique string headers")
    if not set(expected).issubset(values):
        raise CoreError("TABLE_COLUMNS", "Expected columns are absent; do not guess a delimiter/header")
    return list(values)


def _scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        canonical(value)
        return value
    raise CoreError("CELL_TYPE", "Unsupported cell value type")


def parse_bytes(raw, spec):
    """Parser body. CLI calls it in a killed-on-timeout subprocess, not inline."""
    validate_schema("ingest-spec", spec)
    fmt, options, limits = spec["format"], spec["options"], spec["limits"]
    if len(raw) > limits["max_bytes"]:
        raise CoreError("INPUT_LIMIT", "Input exceeds its byte cap", 4)
    fragments, tables, warnings, coverage = [], {}, [], {}
    if fmt in {"md", "txt", "csv", "html_snapshot"}:
        try:
            text = raw.decode(options.get("encoding", "utf-8"), errors="strict")
        except UnicodeError as exc:
            raise CoreError("ENCODING", "Cannot decode input using its explicit encoding") from exc
    if fmt in {"md", "txt"}:
        offset = 0
        for number, line in enumerate(text.splitlines(keepends=True), 1):
            value = line.rstrip("\r\n")
            fragments.append(
                {
                    "kind": "lines",
                    "coordinates": {
                        "start": number,
                        "end": number,
                        "char_start": offset,
                        "char_end": offset + len(value),
                    },
                    "text": value,
                }
            )
            offset += len(line)
        coverage = {"encoding": options.get("encoding", "utf-8"), "characters": len(text), "line_count": len(fragments)}
    elif fmt == "csv":
        delimiter = options.get("delimiter")
        if not delimiter or delimiter in '\r\n\x00"':
            raise CoreError("CSV_DELIMITER", "CSV requires an explicit unambiguous delimiter")
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        columns = _headers(next(reader, []), limits, options.get("expected_columns", []))
        previous_line, rows = reader.line_num, []
        header_end = reader.line_num
        for index, row in enumerate(reader, 1):
            coordinates = {"start": previous_line + 1, "end": reader.line_num, "row": index}
            previous_line = reader.line_num
            if index > limits["max_rows"]:
                raise CoreError("ROWS_LIMIT", "CSV row count exceeds its cap", 4)
            if not row:
                warnings.append("blank_row:" + str(index))
                continue
            if len(row) != len(columns):
                raise CoreError("CSV_WIDTH", "Row width differs from the declared header")
            values = dict(zip(columns, row))
            fragment = canonical(values).decode()
            fragments.append({"kind": "lines", "coordinates": coordinates, "text": fragment})
            rows.append({"row_index": index, "values": values, "coordinates": coordinates, "formula_cells": {}})
        tables["csv"] = {"columns": columns, "rows": rows, "header_coordinates": {"start": 1, "end": header_end}}
        text = "\n".join(fragment["text"] for fragment in fragments)
    elif fmt == "html_snapshot":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else "unknown"
        for node in soup.find_all(["script", "style", "noscript", "template"]):
            node.decompose()
        for index, node in enumerate(soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]), 1):
            value = node.get_text(" ", strip=True)
            if value:
                fragments.append(
                    {
                        "kind": "html",
                        "coordinates": {"tag": node.name, "element": index, "id": node.get("id") or ""},
                        "text": value,
                    }
                )
        text = "\n".join(fragment["text"] for fragment in fragments)
        coverage = {
            "title": title,
            "scripts_executed": False,
            "js_only_supported": False,
            "saved_html_sha256": sha(raw),
        }
    elif fmt == "pdf_text":
        from pypdf import PdfReader

        if not raw.startswith(b"%PDF-"):
            raise CoreError("PDF_CORRUPT", "PDF signature is absent")
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise CoreError("PDF_ENCRYPTED", "Encrypted PDF requires a permitted readable copy", 3)
        if len(reader.pages) > limits["max_pages"]:
            raise CoreError("PAGES_LIMIT", "PDF page count exceeds cap", 4)
        for number, page in enumerate(reader.pages, 1):
            value = page.extract_text() or ""
            if not value.strip():
                warnings.append("page_without_text:" + str(number))
            fragments.append({"kind": "page", "coordinates": {"page": number}, "text": value})
        text = "\n".join(fragment["text"] for fragment in fragments)
        if not text.strip():
            raise CoreError("OCR_REQUIRED", "PDF has no usable text layer; OCR is not implemented", 3)
        warnings.append("complex_pdf_tables_not_verified")
        coverage = {
            "physical_pages": len(reader.pages),
            "ocr_used": False,
            "pages_without_text": sum(not f["text"].strip() for f in fragments),
        }
    elif fmt == "xlsx":
        from openpyxl import load_workbook
        from openpyxl.utils import get_column_letter

        zip_preflight(raw, limits)
        name = options.get("sheet")
        if not name:
            raise CoreError("XLSX_SHEET", "Choose the sheet explicitly")
        formulas = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        cached = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        try:
            if name not in formulas.sheetnames:
                raise CoreError("XLSX_SHEET", "Requested sheet does not exist")
            sheet, values_sheet = formulas[name], cached[name]
            header_row = options.get("header_row", 1)
            if (
                not sheet.max_row
                or not sheet.max_column
                or sheet.max_row > limits["max_rows"] + header_row
                or sheet.max_column > limits["max_columns"]
            ):
                raise CoreError("SHEET_LIMIT", "Workbook dimensions are absent or exceed caps", 4)
            rows_f = list(sheet.iter_rows())
            rows_c = list(values_sheet.iter_rows())
            columns = _headers(
                [cell.value for cell in rows_f[header_row - 1]], limits, options.get("expected_columns", [])
            )
            rows = []
            for row_number in range(header_row + 1, sheet.max_row + 1):
                original, cached_row = rows_f[row_number - 1], rows_c[row_number - 1]
                coordinates = {"sheet": name, "range": f"A{row_number}:{get_column_letter(len(columns))}{row_number}"}
                values, formula_cells = {}, {}
                for column, cell, cache in zip(columns, original, cached_row):
                    if cell.data_type == "f":
                        formula_cells[column] = {
                            "cell": cell.coordinate,
                            "formula": cell.value,
                            "cache_missing": cache.value is None,
                        }
                        warnings.append("formula_not_recalculated:" + cell.coordinate)
                        values[column] = _scalar(cache.value)
                    else:
                        values[column] = _scalar(cell.value)
                if all(value is None for value in values.values()) and not formula_cells:
                    continue
                fragment = canonical(values).decode()
                fragments.append({"kind": "cells", "coordinates": coordinates, "text": fragment})
                rows.append(
                    {
                        "row_index": row_number,
                        "values": values,
                        "coordinates": coordinates,
                        "formula_cells": formula_cells,
                    }
                )
            tables[name] = {
                "columns": columns,
                "rows": rows,
                "header_coordinates": {
                    "sheet": name,
                    "range": f"A{header_row}:{get_column_letter(len(columns))}{header_row}",
                },
            }
            text = "\n".join(fragment["text"] for fragment in fragments)
            coverage = {"sheet": name, "formulas_executed": False, "cache_freshness": "unknown"}
        finally:
            formulas.close()
            cached.close()
    else:
        raise CoreError("FORMAT_UNAVAILABLE", "Unsupported format", 3)
    if not text.strip():
        raise CoreError("EMPTY_EXTRACTION", "Input produced no usable content", 3)
    result = {"text": text, "fragments": fragments, "tables": tables, "warnings": warnings, "coverage": coverage}
    if len(canonical(result)) > limits["max_output_bytes"]:
        raise CoreError("OUTPUT_LIMIT", "Extraction exceeds its output cap", 4)
    return result


def parse_snapshot(raw, spec):
    if spec["format"] in {"image", "scan_pdf", "audio", "video"}:
        from .media import parse

        return parse(raw, spec)
    request = canonical({"raw_base64": base64.b64encode(raw).decode("ascii"), "spec": spec})
    environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "tools.parse_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
    )
    try:
        output, _ = process.communicate(request, timeout=spec["limits"]["timeout_ms"] / 1000)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CoreError("PARSER_TIMEOUT", "Parser exceeded its wall deadline; no retry for this input", 5) from exc
    if len(output) > spec["limits"]["max_output_bytes"] + 4096:
        raise CoreError("OUTPUT_LIMIT", "Parser response exceeds cap", 4)
    if not output:
        raise CoreError("PARSER_FAILED", "Parser exited without a valid receipt", 5)
    response = parse_json(output)
    if not response["ok"]:
        raise CoreError(response["code"], response["reason"], response["exit"])
    return response["data"]


def stage_source(batch, raw, parsed, spec, location, download=None):
    origin = spec["origin"]
    raw_ref = batch.artifact(raw, MIME[spec["format"]], origin)
    identity = digest({"location": location})
    existing = next(
        (
            record
            for record in batch.records.values()
            if record["kind"] == "source"
            and record["revision"] == batch.snapshot["active"].get(record["id"])
            and record["payload"].get("source_identity") == identity
        ),
        None,
    )
    payload = {
        "title": spec["title"],
        "location": location,
        "origin": origin,
        "retrieved_at": now(),
        "published_at": "unknown",
        "sha256": sha(raw),
        "status": "available",
        "rights": spec["rights"],
        "artifact_ref": raw_ref,
        "primary_publication": spec.get("primary_publication", "unknown"),
        "source_identity": identity,
        "format": spec["format"],
        "mime_type": MIME[spec["format"]],
    }
    if download:
        payload["download"] = download
    if existing and existing["payload"]["origin"] != origin:
        raise CoreError("ORIGIN_LAUNDERING", "A source identity cannot silently change its declared origin", 4)
    comparable = lambda value: {k: v for k, v in value.items() if k not in {"retrieved_at", "download"}}
    if existing and comparable(existing["payload"]) == comparable(payload):
        source_ref = ref(existing)
    else:
        source_ref = batch.add("source", payload, existing["id"] if existing else None)
    text_ref = batch.artifact(parsed["text"].encode(), "text/plain", origin, [source_ref])
    ext_payload = {
        "source_ref": source_ref,
        "artifact_ref": text_ref,
        "source_hash": sha(raw),
        "extractor": json.dumps(parser_profile(spec["format"]), sort_keys=True),
        "text": parsed["text"],
        "fragments": parsed["fragments"],
        "warnings": parsed["warnings"],
        "parser_fingerprint": digest(
            {"profile": parser_profile(spec["format"]), "options": spec["options"], "limits": spec["limits"]}
        ),
        "coverage": parsed["coverage"],
    }
    if parsed["tables"]:
        ext_payload["tables_ref"] = batch.artifact(
            canonical({"schema_version": 1, "tables": parsed["tables"]}), "application/json", origin, [source_ref]
        )
    if "_media" in parsed:
        from .media import attach

        ext_payload["coverage"]["media"] = attach(batch, source_ref, parsed["_media"], spec)
    extraction_ref = batch.add("extraction", ext_payload)
    return {
        "source_ref": source_ref,
        "extraction_ref": extraction_ref,
        "source_sha256": sha(raw),
        "warnings": parsed["warnings"],
        "table_names": list(parsed["tables"]),
    }


def ingest(store, filename, spec, expected):
    validate_schema(
        "media-spec"
        if isinstance(spec, dict) and spec.get("format") in {"image", "scan_pdf", "audio", "video"}
        else "ingest-spec",
        spec,
    )
    if not spec["rights"]["processing"]:
        raise CoreError("PROCESSING_DENIED", "No permission to process the material", 4)
    filename, policy = allowed_input(store, filename)
    if filename.startswith("tests/fixtures/") and spec["origin"] != "synthetic_fixture":
        raise CoreError("FIXTURE_ORIGIN", "Technical fixtures must retain synthetic provenance", 4)
    status = store.status()
    if status["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read a fresh case revision before ingestion", 7)
    try:
        raw = store.io.read(filename, min(spec["limits"]["max_bytes"], policy["max_input_bytes"]))
    except FileNotFoundError as exc:
        raise CoreError("INPUT_MISSING", "Input file is absent") from exc
    profile = parser_profile(spec["format"])
    request = {"path": filename, "sha256": sha(raw), "spec": spec, "parser": profile, "policy_sha256": digest(policy)}

    def builder(snapshot):
        batch = RecordBatch(store, snapshot)
        # The accepted-operation check precedes parsing; errors enter the journal.
        parsed = parse_snapshot(raw, spec)
        data = stage_source(batch, raw, parsed, spec, filename)
        return batch.finish(data)

    return store._mutate(
        "ingest",
        request,
        expected,
        builder,
        reuse_if=lambda snapshot, data: (
            snapshot["active"].get(data["source_ref"]["entity_id"]) == data["source_ref"]["revision"]
        ),
    )


def search_local(store, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise CoreError("QUERY_INVALID", "Use a nonempty bounded text query")
    tokens = set(re.findall(r"\w+", query.casefold()))
    if not tokens or len(tokens) > 16:
        raise CoreError("QUERY_LIMIT", "Use one to sixteen search tokens")
    with store.io.lock(store.lock_path):
        snapshot, warnings, _ = store._load()
        records = store.records(snapshot)
        candidates = {}
        for record in records.values():
            if record["kind"] != "extraction":
                continue
            source_ref = record["payload"]["source_ref"]
            source = records[key(source_ref)]
            if (
                snapshot["active"].get(source["id"]) != source_ref["revision"]
                or source["payload"]["status"] != "available"
                or not source["payload"]["rights"]["processing"]
            ):
                continue
            selection = (source["id"], record["payload"].get("coverage", {}).get("sheet", "text"))
            prior = candidates.get(selection)
            if prior is None or int(record["id"].split("-")[1]) > int(prior["id"].split("-")[1]):
                candidates[selection] = record
        hits = []
        for record in candidates.values():
            source = records[key(record["payload"]["source_ref"])]
            for fragment in record["payload"]["fragments"]:
                score = sum(token in fragment["text"].casefold() for token in tokens)
                if score:
                    hits.append(
                        {
                            "score": score,
                            "source_ref": ref(source),
                            "extraction_ref": ref(record),
                            "origin_roots": record["lineage_roots"],
                            "primary_publication": source["payload"].get("primary_publication", "unknown"),
                            "raw_artifact_ref": source["payload"].get("artifact_ref"),
                            "status": source["payload"]["status"],
                            "retrieved_at": source["payload"]["retrieved_at"],
                            "locator": {
                                "source_revision": source["revision"],
                                "source_hash": source["payload"]["sha256"],
                                "extraction_id": record["id"],
                                "kind": fragment["kind"],
                                "coordinates": fragment["coordinates"],
                                "exact_quote": fragment["text"],
                            },
                        }
                    )
        hits.sort(
            key=lambda hit: (-hit["score"], hit["source_ref"]["entity_id"], canonical(hit["locator"]["coordinates"]))
        )
        return {
            "case_revision": snapshot["case_revision"],
            "warnings": warnings,
            "data": {"mode": "local_lexical", "hits": hits[:20], "discovery_performed": False},
        }
