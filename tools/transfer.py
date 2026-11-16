"""Hash-checked local backup/import; no code execution or silent namespace conversion."""

from io import BytesIO
import stat
import zipfile
import re
import uuid
from pathlib import Path

from .contracts import case_slug, digest, sha, key, ref
from .errors import CoreError
from .safeio import SafeRoot, canonical, parse_json, parts
from .store import Store

CAP = 64 * 1024 * 1024


def read_member(archive, name, limit):
    data = bytearray()
    with archive.open(name) as stream:
        while True:
            block = stream.read(min(65536, limit - len(data) + 1))
            if not block:
                break
            data.extend(block)
            if len(data) > limit:
                raise CoreError("ARCHIVE_LIMIT", "Expanded ZIP member exceeds remaining budget", 4)
    return bytes(data)


def scoped_transfer(store, snapshot, records, approval_id, destination):
    """Additional exact local grant; never upgrades historical source rights."""
    revision = snapshot["active"].get(approval_id)
    record = records.get(f"{approval_id}@{revision}")
    if not record or record["kind"] != "approval":
        raise CoreError("TRANSFER_APPROVAL", "Select a committed current APR receipt", 4)
    grant = record["payload"]
    terms = grant.get("terms", {})
    required = {
        "contract": "scoped-local-transfer-v1",
        "local_history_copy": True,
        "model_input": "deidentified_synthetic_text_only",
        "provider": "OpenAI/ChatGPT",
        "host": "codex",
        "model_call_cap": 1,
        "raw_media_external": False,
        "publication": False,
    }
    if (
        grant.get("scope") != "data_transfer"
        or grant.get("status") != "approve"
        or grant.get("approval_kind") != "real"
    ):
        raise CoreError("TRANSFER_APPROVAL", "A real approved data-transfer receipt is required", 4)
    if any(terms.get(k) != v for k, v in required.items()):
        raise CoreError("TRANSFER_SCOPE", "Grant is not the bounded local-copy/text-only contract", 4)
    target = str(Path(destination).resolve())
    if terms.get("source_root_sha256") != sha(str(store.io.path).encode()) or terms.get(
        "destination_root_sha256"
    ) != sha(target.encode()):
        raise CoreError("TRANSFER_DESTINATION", "Grant must match the actual source and destination roots", 4)
    proposal = records.get(key(terms.get("proposal_ref", {})))
    if not proposal or proposal["kind"] != "artifact" or proposal["payload"]["sha256"] != terms.get("proposal_sha256"):
        raise CoreError("TRANSFER_PROPOSAL", "Grant does not bind the immutable proposal", 4)
    # Store validates receipt/request/terms/digest and human evidence on load.
    # Inspect the proposal bytes too: an editable archive flag is never authority.
    proposed = parse_json(store.blob(proposal["payload"]["sha256"]))
    inventory = [{"ref": ref(r), "sha256": r["payload"]["sha256"]} for r in records.values() if r["kind"] == "source"]
    wanted = terms.get("source_inventory", [])
    proposed_inventory = [{"ref": r["ref"], "sha256": r["sha256"]} for r in proposed["source_inventory"]]
    ordered = lambda rows: sorted((canonical(row) for row in rows))
    if ordered(inventory) != ordered(wanted) or ordered(inventory) != ordered(proposed_inventory):
        raise CoreError("TRANSFER_INVENTORY", "Grant must cover every exact source revision/hash, with no extras", 4)
    if any(
        r["payload"]["origin"] != "synthetic_fixture" or not r["payload"]["rights"]["processing"]
        for r in records.values()
        if r["kind"] == "source"
    ):
        raise CoreError("TRANSFER_SCOPE", "This grant covers owned synthetic processing-permitted sources only", 4)
    if set(key(r) for r in grant["targets"]) != {key(terms["proposal_ref"]), *(key(r["ref"]) for r in inventory)}:
        raise CoreError("TRANSFER_TARGETS", "Grant targets differ from the full pinned inventory/proposal", 4)
    return {
        "approval_ref": ref(record),
        "approval_record_sha256": digest(record),
        "destination_root_sha256": sha(target.encode()),
        "source_inventory_digest": digest(sorted(inventory, key=lambda r: key(r["ref"]))),
    }


def export_case(store, mode, out, approval=None, destination=None):
    components = parts(out)
    if tuple(components[:2]) != ("output", "backups") or len(components) != 3 or not out.endswith(".zip"):
        raise CoreError("EXPORT_PATH", "Local bundles must be a direct output/backups/*.zip path", 4)
    if mode not in {"backup", "public"}:
        raise CoreError("EXPORT_MODE", "Choose backup or public")
    with store.io.lock(store.lock_path):
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        sources = [r for r in records.values() if r["kind"] == "source"]
        if bool(approval) != bool(destination) or (approval and mode != "backup"):
            raise CoreError(
                "TRANSFER_SCOPE", "Scoped transfer requires backup mode, --approval and --destination together", 4
            )
        authorization = scoped_transfer(store, snapshot, records, approval, destination) if approval else None
        if mode == "public" and any(not r["payload"]["rights"]["publication"] for r in sources):
            raise CoreError(
                "PUBLICATION_DENIED",
                "Public export would contain sources without publication rights; no data silently removed from reproducible bundle",
                4,
            )
        files = {store.events: store.io.read(store.events, CAP)}
        for row in store.rows:
            if row["type"] == "ERROR" and row.get("quarantine"):
                name = row["quarantine"]
                parts(name)
                if not name.startswith(store.base + "/journal/tail-"):
                    raise CoreError("QUARANTINE_PATH", "Tail path outside journal", 6)
                tail = store.io.read(name, CAP)
                if sha(tail) != row.get("sha256_tail"):
                    raise CoreError("QUARANTINE_HASH", "Saved diagnostic tail changed", 6)
                files[name] = tail
            if row["type"] == "PREPARE":
                # Include committed manifests only; an incomplete PREPARE stays in
                # the journal but is not accepted by the restored snapshot.
                committed = any(r["type"] == "COMMIT" and r.get("prepare_hash") == row["sha256"] for r in store.rows)
                if committed:
                    for name in row["files"]:
                        files[name] = store.io.read(name, CAP)
        if len(files) > 10000 or sum(map(len, files.values())) > CAP:
            raise CoreError("EXPORT_LIMIT", "Backup exceeds bounded manifest/size limit", 4)
        transferable = all(r["payload"]["rights"]["external_transfer"] for r in sources)
        manifest = {
            "format": 1,
            "case_id": store.case_id,
            "namespace": snapshot["namespace"],
            "case_revision": snapshot["case_revision"],
            "snapshot_digest": digest(snapshot),
            "mode": mode,
            "external_transfer_allowed": transferable,
            "local_root_sha256": sha(str(store.io.path).encode()) if hasattr(store.io, "path") else None,
            "files": {n: sha(raw) for n, raw in files.items()},
            "limitations": "No credentials/machine capabilities/locks. A local backup is not publication or approval to transfer restricted data.",
        }
        # Record the actual root through descriptor-safe helper's public root path.
        manifest["local_root_sha256"] = sha(str(store.io.path).encode())
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in [("manifest.json", canonical(manifest)), *sorted(files.items())]:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        raw = buffer.getvalue()
        if authorization:
            store.io.write(
                ".local/transfer-receipts/" + sha(raw) + ".json",
                canonical(
                    {
                        **authorization,
                        "archive_sha256": sha(raw),
                        "snapshot_digest": digest(snapshot),
                        "case_id": store.case_id,
                        "source_root_sha256": sha(str(store.io.path).encode()),
                    }
                ),
                immutable=True,
            )
        if store.io.exists(out):
            if store.io.read(out, CAP) == raw:
                return {
                    "case_revision": snapshot["case_revision"],
                    "data": {"out": out, "sha256": sha(raw), "reused": True},
                }
            raise CoreError("EXPORT_EXISTS", "Existing bundle is different; use a new explicit filename", 7)
        store.io.write(out, raw, immutable=True)
        store.io.write(
            ".local/backup-receipts/" + sha(raw) + ".json",
            canonical(
                {
                    "archive_sha256": sha(raw),
                    "snapshot_digest": digest(snapshot),
                    "case_id": store.case_id,
                    "root_sha256": sha(str(store.io.path).encode()),
                }
            ),
            immutable=True,
        )
    return {
        "case_revision": snapshot["case_revision"],
        "data": {
            "out": out,
            "sha256": sha(raw),
            "file_count": len(files),
            "external_transfer_allowed": transferable,
            "local_only": not transferable,
            "publication_performed": False,
            "scoped_transfer": authorization,
        },
    }


def import_case(
    project, bundle, case_id, namespace, authorization_project=None, approval=None, trusted_bundle_sha256=None
):
    """Restore immutable history; an explicit digest attests LOCAL synthetic processing only.

    The digest must come from the user out of band, not from the ZIP manifest.
    It neither authenticates a rightsholder nor authorizes model input/publication.
    """
    case_slug(case_id)
    if namespace not in {"test", "demo", "official"} or (namespace == "test") != case_id.startswith("test-"):
        raise CoreError("NAMESPACE", "Logical case ID must retain its original test/demo/official namespace", 4)
    if bool(authorization_project) != bool(approval):
        raise CoreError("TRANSFER_APPROVAL", "--authorization-project and --approval are required together", 4)
    if trusted_bundle_sha256 is not None and authorization_project:
        raise CoreError("TRANSFER_SCOPE", "Choose either scoped owner authorization or local digest consent", 4)
    with SafeRoot(project) as root:
        components = parts(bundle)
        if tuple(components[:2]) not in {("output", "backups"), ("input", "backups")}:
            raise CoreError("IMPORT_PATH", "Bundle must be under input/backups or output/backups", 4)
        raw = root.read(bundle, CAP)
        archive_sha256 = sha(raw)
        if trusted_bundle_sha256 is not None and (
            not isinstance(trusted_bundle_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", trusted_bundle_sha256) is None
            or trusted_bundle_sha256 != archive_sha256
        ):
            raise CoreError("TRUSTED_BUNDLE_HASH", "User-supplied full archive SHA-256 must match exactly", 4)
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                entries = archive.infolist()
                names = [e.filename for e in entries]
                if len(names) != len(set(names)) or len(names) > 10001:
                    raise CoreError("ARCHIVE_LIMIT", "Duplicate/too many ZIP entries", 4)
                if sum(e.file_size for e in entries) > CAP:
                    raise CoreError("ARCHIVE_LIMIT", "Expanded backup exceeds cap", 4)
                for e in entries:
                    parts(e.filename)
                    if e.flag_bits & 1 or stat.S_ISLNK(e.external_attr >> 16) or e.is_dir():
                        raise CoreError("ARCHIVE_UNSAFE", "Encrypted/symlink/directory entries are not supported", 4)
                    if e.file_size > 1024 * 1024 and e.file_size / max(1, e.compress_size) > 200:
                        raise CoreError("ARCHIVE_LIMIT", "Archive expansion ratio exceeds cap", 4)
                manifest = parse_json(read_member(archive, "manifest.json", 2 * 1024 * 1024))
                if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
                    raise CoreError("IMPORT_CORRUPT", "Backup manifest must contain a file hash mapping", 6)
                if manifest.get("format") != 1:
                    raise CoreError("IMPORT_VERSION", "Unknown export format", 6)
                if manifest["case_id"] != case_id or manifest["namespace"] != namespace:
                    raise CoreError("IMPORT_IDENTITY", "Logical case ID and namespace must remain unchanged", 4)
                if set(names) != {"manifest.json", *manifest["files"]}:
                    raise CoreError("ARCHIVE_MANIFEST", "Archive entries differ from manifest", 6)
                payload = {}
                remaining = CAP
                prefix = "cases/" + case_id + "/"
                for name, expected in manifest["files"].items():
                    if not name.startswith(prefix) or not any(
                        name[len(prefix) :].startswith(p)
                        for p in ("records/", "artifacts/sha256/", "journal/", "events.jsonl")
                    ):
                        raise CoreError("ARCHIVE_PATH", "Archive member is outside immutable case history", 4)
                    content = read_member(archive, name, remaining)
                    remaining -= len(content)
                    if sha(content) != expected:
                        raise CoreError("IMPORT_HASH", "Archive member hash differs", 6)
                    payload[name] = content
        except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as error:
            raise CoreError("IMPORT_CORRUPT", "Invalid backup structure; nothing overwritten", 6) from error
        # Destination-managed staging is on the target filesystem, pinned by fd.
        # Retain failed stages for diagnosis; never recursively delete a case.
        stage_path = ".local/import-staging/" + uuid.uuid4().hex
        root.mkdir_exclusive(stage_path)
        with root.subroot(stage_path) as staging:
            for name, content in payload.items():
                staging.write(name, content, immutable=True)
            with Store(staging, case_id) as staged:
                snapshot, _, _ = staged._load(check_projection=False)
                if digest(snapshot) != manifest["snapshot_digest"] or snapshot["namespace"] != namespace:
                    raise CoreError("IMPORT_SNAPSHOT", "Restored snapshot or namespace differs", 6)
                records = staged.records(snapshot)
                transferable = all(
                    r["payload"]["rights"]["external_transfer"] for r in records.values() if r["kind"] == "source"
                )
                authorized = None
                if authorization_project:
                    # Trust comes from the explicitly selected original local Store
                    # and its export receipt OUTSIDE the archive, not manifest flags.
                    with Store(authorization_project, case_id) as source:
                        with source.io.lock(source.lock_path):
                            current, _, _ = source._load()
                            source_records = source.records(current)
                            authorized = scoped_transfer(source, current, source_records, approval, root.path)
                            receipt = source.io.json(".local/transfer-receipts/" + sha(raw) + ".json")
                            expected = {
                                **authorized,
                                "archive_sha256": sha(raw),
                                "snapshot_digest": digest(snapshot),
                                "case_id": case_id,
                                "source_root_sha256": sha(str(source.io.path).encode()),
                            }
                            if receipt != expected:
                                raise CoreError(
                                    "TRANSFER_RECEIPT",
                                    "Original export receipt does not match archive/destination/grant",
                                    4,
                                )
                            pinned = authorized["approval_ref"]
                            if records.get(key(pinned)) != source_records[key(pinned)]:
                                raise CoreError(
                                    "TRANSFER_APPROVAL", "Imported history does not contain the authorized receipt", 4
                                )
                            staged_inventory = [
                                {"ref": ref(r), "sha256": r["payload"]["sha256"]}
                                for r in records.values()
                                if r["kind"] == "source"
                            ]
                            if (
                                digest(sorted(staged_inventory, key=lambda r: key(r["ref"])))
                                != authorized["source_inventory_digest"]
                            ):
                                raise CoreError(
                                    "TRANSFER_INVENTORY", "Archive source inventory differs from authorized source", 4
                                )
                local_consent = None
                if trusted_bundle_sha256 is not None:
                    sources = [r for r in records.values() if r["kind"] == "source"]
                    if not sources or any(
                        r["payload"]["origin"] != "synthetic_fixture"
                        or r["payload"]["rights"]["processing"] is not True
                        or set(r["lineage_roots"]) - {"synthetic_fixture", "model_simulation"}
                        for r in sources
                    ):
                        raise CoreError(
                            "LOCAL_CONSENT_SCOPE",
                            "Digest consent covers processing-permitted synthetic sources only",
                            4,
                        )
                    local_consent = {
                        "contract": "local-synthetic-restore-v1",
                        "attestation": "explicit_user_supplied_archive_digest",
                        "archive_sha256": archive_sha256,
                        "snapshot_digest": digest(snapshot),
                        "case_id": case_id,
                        "namespace": namespace,
                        "destination_root_sha256": sha(str(root.path).encode()),
                        "source_inventory_digest": digest(
                            sorted(
                                [{"ref": ref(r), "sha256": r["payload"]["sha256"]} for r in sources],
                                key=lambda row: key(row["ref"]),
                            )
                        ),
                        "local_processing": True,
                        "model_transfer": False,
                        "publication": False,
                        "rightsholder_identity_verified": False,
                        "historical_rights_unchanged": True,
                    }
                if not transferable and not authorized and not local_consent:
                    receipt_path = ".local/backup-receipts/" + sha(raw) + ".json"
                    if not root.exists(receipt_path):
                        raise CoreError(
                            "TRANSFER_DENIED",
                            "Restricted data requires trusted local export receipt outside archive; another root is not authorized",
                            4,
                        )
                    expected = {
                        "archive_sha256": sha(raw),
                        "snapshot_digest": digest(snapshot),
                        "case_id": case_id,
                        "root_sha256": sha(str(root.path).encode()),
                    }
                    if root.json(receipt_path) != expected:
                        raise CoreError("TRANSFER_DENIED", "Local receipt differs from actual root/archive", 4)
                for row in staged.rows:
                    if row["type"] == "ERROR" and row.get("quarantine"):
                        if row["quarantine"] not in payload or sha(payload[row["quarantine"]]) != row.get(
                            "sha256_tail"
                        ):
                            raise CoreError("QUARANTINE_HASH", "Backup omitted/changed diagnostic tail", 6)
                accepted_files = {staged.events}
                committed = {row.get("prepare_hash") for row in staged.rows if row["type"] == "COMMIT"}
                for row in staged.rows:
                    if row["type"] == "PREPARE" and row["sha256"] in committed:
                        accepted_files.update(row["files"])
                    if row["type"] == "ERROR" and row.get("quarantine"):
                        accepted_files.add(row["quarantine"])
                if set(payload) != accepted_files:
                    raise CoreError(
                        "ARCHIVE_MANIFEST", "Backup includes files outside committed history/diagnostic tails", 6
                    )
                projections = staged._projection_bytes(snapshot)
                for name, content in projections.items():
                    staging.write("cases/" + case_id + "/" + name, content)
                # Verify the complete install image, including rebuilt projections.
                _, warnings, _ = staged._load()
                if warnings:
                    raise CoreError("IMPORT_PROJECTIONS", "Staged projections did not validate", 6)
            with root.lock("cases/.locks/" + case_id + ".lock"):
                if root.exists("cases/" + case_id):
                    raise CoreError("IMPORT_EXISTS", "Never overwrite an existing case", 7)
                consent_path = None
                if local_consent:
                    consent_path = ".local/import-consents/" + archive_sha256 + ".json"
                    root.write(consent_path, canonical(local_consent), immutable=True)
                try:
                    root.promote_directory(stage_path + "/cases/" + case_id, "cases/" + case_id)
                except CoreError as error:
                    if error.code == "DIRECTORY_DURABILITY_UNKNOWN":
                        error.saved = "Target may already be complete; preserve target and staging"
                        error.next_action = "Reconcile target read-only with status/validate; do not retry import"
                        error.data = {
                            "target": "cases/" + case_id,
                            "staging": stage_path,
                            "archive_sha256": archive_sha256,
                            "snapshot_digest": digest(snapshot),
                            "local_consent_receipt": consent_path,
                        }
                    raise
                return {
                    "case_revision": snapshot["case_revision"],
                    "data": {
                        "case_id": case_id,
                        "namespace": namespace,
                        "snapshot_digest": digest(snapshot),
                        "capabilities_inherited": False,
                        "credentials_imported": False,
                        "scoped_transfer": authorized,
                        "local_consent_receipt": consent_path,
                    },
                }
