"""JSON-only command interface; no strategic decisions and no agent loop."""

import argparse
import importlib.metadata
import os
from pathlib import Path
import sys
import time
import uuid

from .contracts import CLI_KINDS, case_slug, schema_registry
from .errors import CoreError
from .safeio import SafeRoot
from .store import Store, now, unknown_usage


class HelpRequested(Exception):
    def __init__(self, text):
        self.text = text


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CoreError("ARGUMENTS", "Invalid command/arguments; read --help")

    def _print_message(self, message, file=None):
        self._help_text = getattr(self, "_help_text", "") + (message or "")

    def exit(self, status=0, message=None):
        if status == 0:
            raise HelpRequested(getattr(self, "_help_text", "") or self.format_help())
        raise CoreError("ARGUMENTS", "Invalid command/arguments; read --help")


def parser():
    root = Parser(description="Local evidence core and bounded sources/metrics. All output including --help is JSON.")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Local diagnostics; no installs, network or paid probes")
    doctor.add_argument("--case", type=case_slug)
    doctor.add_argument("--live")
    doctor.add_argument("--approval")
    doctor.add_argument("--expected-revision", type=int)
    for name in ("init", "status", "validate", "record", "checkpoint", "recover"):
        sub = commands.add_parser(name)
        sub.add_argument("--case", required=True, type=case_slug)
        if name == "init":
            sub.add_argument("--namespace", required=True, choices=("test", "demo", "official"))
        if name in ("record", "checkpoint", "recover"):
            sub.add_argument("--expected-revision", type=int, required=name != "recover")
        if name == "record":
            sub.add_argument("--kind", required=True, choices=CLI_KINDS)
            sub.add_argument("--file", required=True)
        if name == "checkpoint":
            sub.add_argument("--reason", required=True)
        if name == "recover":
            sub.add_argument("--repair-tail", action="store_true")
    approval = commands.add_parser("approval")
    approval_commands = approval.add_subparsers(dest="approval_command", required=True)
    for name in ("request", "record"):
        sub = approval_commands.add_parser(name)
        sub.add_argument("--case", required=True, type=case_slug)
        sub.add_argument("--file", required=True)
        sub.add_argument("--expected-revision", required=True, type=int)
    for name in ("ingest", "fetch", "metrics", "search"):
        sub = commands.add_parser(name)
        sub.add_argument("--case", required=True, type=case_slug)
        if name == "search":
            sub.add_argument("--query", required=True)
            sub.add_argument("--discovery", action="store_true", help="Unavailable: no verified discovery adapter")
            sub.add_argument("--approval")
            sub.add_argument("--expected-revision", type=int)
        else:
            sub.add_argument("--spec", required=True, help="JSON spec in an allowed input root")
            sub.add_argument("--expected-revision", required=True, type=int)
        if name == "ingest":
            sub.add_argument("--path", required=True)
        if name == "fetch":
            sub.add_argument("--url", required=True, help="Known exact HTTPS URL; requires real scoped approvals")
    for group, operations in [
        ("route", ("plan", "run", "accept")),
        ("review", ("run", "import")),
        ("mcp", ("probe", "call")),
        ("hook", ("run",)),
    ]:
        parent = commands.add_parser(group)
        nested = parent.add_subparsers(dest="integration_command", required=True)
        for name in operations:
            sub = nested.add_parser(name)
            sub.add_argument("--case", required=True, type=case_slug)
            sub.add_argument(
                "--file" if name in {"accept", "import"} else "--spec",
                required=True,
                help="Pinned JSON request under case input/requests",
            )
            if name != "plan":
                sub.add_argument("--expected-revision", required=True, type=int)
            if group in {"route", "review", "mcp"}:
                sub.add_argument(
                    "--approval",
                    help="Reserved for actual externally approved adapters; host bridge does not manufacture approvals",
                )
            if group == "review" and name == "run":
                sub.add_argument("--provider", choices=("host", "openai"), default="host")
            if group == "route" and name == "run":
                sub.add_argument(
                    "--provider",
                    choices=("host", "opencode"),
                    default="host",
                    help="host prepares manual dispatch; opencode executes one task through existing approved sign-in",
                )
    for name in ("impact", "agenda", "retract", "retrieve", "export", "index", "import-case"):
        sub = commands.add_parser(name)
        sub.add_argument("--case", required=True, type=case_slug)
        if name == "impact":
            sub.add_argument("--claim", required=True)
        if name == "agenda":
            sub.add_argument("--as-of", required=True)
        if name == "retract":
            sub.add_argument("--file", required=True)
        if name == "retrieve":
            sub.add_argument("--query", required=True)
            sub.add_argument("--mode", choices=("lexical", "hybrid"), default="lexical")
            sub.add_argument("--history", action="store_true")
        if name == "export":
            sub.add_argument("--mode", choices=("backup", "public"), required=True)
            sub.add_argument("--out", required=True)
            sub.add_argument(
                "--approval", help="Real scoped data-transfer APR, used with --destination for local backup transfer"
            )
            sub.add_argument(
                "--destination", help="Exact authorized destination project root; does not grant publication"
            )
        if name == "index":
            sub.add_argument("index_command", choices=("build",))
            sub.add_argument("--spec", required=True)
        if name == "import-case":
            sub.add_argument("--bundle", required=True)
            sub.add_argument("--namespace", choices=("test", "demo", "official"), required=True)
            sub.add_argument(
                "--authorization-project",
                help="Original trusted local project with immutable export receipt, never the extracted ZIP",
            )
            sub.add_argument("--approval", help="Matching real scoped data-transfer APR from the original project")
            sub.add_argument(
                "--trusted-bundle-sha256",
                help="Explicit out-of-band SHA-256 consent for local synthetic-demo restore only; no model/publication rights",
            )
        if name in {"retract", "index"}:
            sub.add_argument("--expected-revision", required=True, type=int)
    return root


def input_json(project, case_id, filename):
    from .safeio import parts

    components = parts(filename)
    allowed = [
        ("cases", case_id, "input"),
        ("cases", case_id, "requests"),
        ("tests", "fixtures", "core"),
        ("tests", "specs"),
    ]
    if not any(tuple(components[: len(prefix)]) == prefix and len(components) > len(prefix) for prefix in allowed):
        raise CoreError(
            "INPUT_ROOT", "JSON inputs must be inside this case input/requests or approved core fixtures", 4
        )
    with SafeRoot(project) as root:
        try:
            return root.json(filename)
        except FileNotFoundError as exc:
            raise CoreError("INPUT_MISSING", "Requested JSON input file is missing") from exc


def doctor(project, args):
    if args.live == "formats":
        if not args.case or not args.approval or args.expected_revision is None:
            raise CoreError(
                "APPROVAL_REQUIRED",
                "doctor --live formats requires --case, --approval APR-id and fresh --expected-revision",
                3,
            )
        from .formats_probe import run

        with Store(project, args.case) as store:
            return run(store, args.approval, args.expected_revision)
    versions = {}
    for name in ("jsonschema", "pytest", "pypdf", "openpyxl", "beautifulsoup4"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    if sys.version_info < (3, 11) or os.name != "posix":
        raise CoreError("PLATFORM_UNAVAILABLE", "Core currently requires Python 3.11+ and a local POSIX filesystem", 3)
    schemas, _ = schema_registry()
    with SafeRoot(project) as root:
        config = {
            name: root.json("config/" + name + ".json")
            for name in ("gates", "source_policy", "budget", "adapters.example")
        }
    if any(value.get("schema_version") != 1 for value in config.values()):
        raise CoreError("CONFIG_VERSION", "Unknown configuration schema version")
    if args.live:
        raise CoreError(
            "LIVE_UNIMPLEMENTED",
            "Doctor performs no live probes; use fetch with real URL-scoped approvals",
            3,
            next_action="Implement the relevant later step and obtain R/P approvals",
        )
    data = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "packages": versions,
        "local_schema_count": len(schemas),
        "network_used": False,
        "gates": {name: gate["status"] for name, gate in config["gates"]["gates"].items()},
        "capabilities": {
            name: {"status": "not_implemented", "live_verified": False}
            for name in (
                "ingest",
                "fetch",
                "metrics",
                "ocr",
                "stt",
                "video",
                "reviewer",
                "mcp",
                "embeddings",
                "second_host",
            )
        },
    }
    for name in ("ingest", "metrics"):
        data["capabilities"][name]["status"] = "implemented_local_unverified_here"
    data["capabilities"]["fetch"]["status"] = "implemented_permission_gated"
    for name in ("ocr", "video"):
        data["capabilities"][name]["status"] = "implemented_local_engine_required"
    from .diagnostics import diagnostics

    report = diagnostics(project)
    data["capabilities"].update(report.pop("capabilities"))
    data.update(report)
    if args.case:
        with Store(project, args.case) as store:
            result = store.status()
        data["case"] = result["data"]
        return {**result, "data": data}
    return {"data": data}


def dispatch(project, args):
    if args.command == "import-case":
        from .transfer import import_case

        return import_case(
            project,
            args.bundle,
            args.case,
            args.namespace,
            args.authorization_project,
            args.approval,
            trusted_bundle_sha256=args.trusted_bundle_sha256,
        )
    if args.command == "doctor":
        return doctor(project, args)
    with Store(project, args.case) as store:
        if args.command in {"impact", "agenda", "retract"}:
            from .graph import impact, agenda, retract

            if args.command == "impact":
                return impact(store, args.claim)
            if args.command == "agenda":
                return agenda(store, args.as_of)
            return retract(store, input_json(project, args.case, args.file), args.expected_revision)
        if args.command in {"retrieve", "index"}:
            from .search import retrieve, build

            if args.command == "retrieve":
                return retrieve(store, args.query, args.mode, args.history)
            return build(store, input_json(project, args.case, args.spec), args.expected_revision)
        if args.command == "export":
            from .transfer import export_case

            return export_case(store, args.mode, args.out, args.approval, args.destination)
        if args.command in {"route", "review", "mcp", "hook"}:
            operation = args.integration_command
            request = input_json(project, args.case, args.file if operation in {"accept", "import"} else args.spec)
            if args.command == "route":
                from .routing import plan, prepare, accept

                if operation == "plan":
                    return plan(store, request)
                if operation == "run" and args.provider == "opencode":
                    from .adapters.opencode_model import execute as host_execute

                    return host_execute(store, request, args.expected_revision)
                return (accept if operation == "accept" else prepare)(store, request, args.expected_revision)
            if args.command == "review":
                if operation == "import":
                    return store.record("review", {"payload": request}, args.expected_revision)
                if args.provider != "host":
                    raise CoreError(
                        "MODEL_API_BLOCKED",
                        "No approved endpoint, model, budget or external data transfer; host bridge only",
                        3,
                    )
                from .routing import prepare

                if request.get("task_type") != "independent_review":
                    raise CoreError("REVIEW_SPEC", "Review dispatch needs independent_review task type")
                return prepare(store, request, args.expected_revision)
            if args.command == "mcp":
                from .adapters.mcp_client import execute as mcp_execute

                return mcp_execute(store, request, args.expected_revision, operation)
            from hooks.checks import run

            return run(store, request, args.expected_revision)
        if args.command == "init":
            return store.init(args.namespace)
        if args.command == "status":
            return store.status()
        if args.command == "validate":
            return store.validate()
        if args.command == "checkpoint":
            return store.checkpoint(args.reason, args.expected_revision)
        if args.command == "recover":
            if args.repair_tail and args.expected_revision is None:
                raise CoreError("EXPECTED_REVISION", "Explicit tail repair needs the diagnosed revision")
            return store.recover(args.expected_revision, args.repair_tail)
        if args.command == "search":
            if args.discovery:
                raise CoreError("DISCOVERY_UNAVAILABLE", "No verified discovery adapter; local lexical search only", 3)
            from .sources import search_local

            return search_local(store, args.query)
        if args.command in {"ingest", "fetch", "metrics"}:
            spec = input_json(project, args.case, args.spec)
            if args.command == "ingest":
                from .sources import ingest

                return ingest(store, args.path, spec, args.expected_revision)
            if args.command == "fetch":
                from .safe_fetch import fetch

                return fetch(store, args.url, spec, args.expected_revision)
            from .calculations import metrics

            return metrics(store, spec, args.expected_revision)
        request = input_json(project, args.case, args.file)
        if args.command == "approval":
            payload = request.get("payload", {}) if isinstance(request, dict) else {}
            if (args.approval_command == "request") != (payload.get("status") == "requested"):
                raise CoreError("APPROVAL_OPERATION", "Request/record subcommand does not match the receipt status")
            return store.record("approval", request, args.expected_revision)
        return store.record(args.kind, request, args.expected_revision)


def main(argv=None):
    started = time.monotonic()
    result = {
        "ok": False,
        "code": "INTERNAL_ERROR",
        "action_id": None,
        "attempt_id": None,
        "case_revision": None,
        "data": None,
        "warnings": [],
        "error": None,
    }
    exit_code = 0
    try:
        args = parser().parse_args(argv)
        data = dispatch(Path.cwd(), args)
        result.update(ok=True, code="OK", **data)
    except HelpRequested as help_request:
        result.update(ok=True, code="HELP", data={"help": help_request.text})
    except CoreError as exc:
        if (
            "args" in locals()
            and args.command in {"ingest", "fetch", "metrics", "search"}
            and not getattr(exc, "journaled", False)
        ):
            try:
                from .contracts import digest

                with Store(Path.cwd(), args.case) as store:
                    store.note_failure(args.command, digest(vars(args)), exc, getattr(args, "expected_revision", None))
            except (CoreError, OSError):
                pass  # Logging must not repair/overwrite a damaged case.
        exit_code = exc.exit_code
        result.update(
            code=exc.code,
            data=exc.data,
            error={"reason": exc.reason, "saved": exc.saved, "next_action": exc.next_action},
        )
    except (OSError, UnicodeError):
        exit_code = 6
        result.update(
            code="IO_FAILURE",
            error={
                "reason": "Local I/O failed; content was not reset",
                "saved": "Inspect the last durable commit",
                "next_action": "Check permissions and recover read-only",
            },
        )
    except Exception as exc:
        exit_code = 6
        print("Internal diagnostic type: " + type(exc).__name__, file=sys.stderr)
        result.update(
            code="INTERNAL_ERROR",
            error={
                "reason": "Unexpected internal failure; preserve case files",
                "saved": "Inspect the last durable commit",
                "next_action": "Run tests and recover read-only before continuing",
            },
        )
    if result["ok"] and isinstance(result["data"], dict):
        result["data"]["telemetry"] = {
            "receipt_id": str(uuid.uuid4()),
            "at": now(),
            "usage": unknown_usage((time.monotonic() - started) * 1000),
            "persisted": False,
            "committed_action_id": result["action_id"],
        }
    from .safeio import canonical

    print(canonical(result).decode())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
