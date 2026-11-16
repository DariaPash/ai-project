"""Stage a small deterministic record batch for the existing Store COMMIT."""

from .contracts import key, ref, sha
from .errors import CoreError


class RecordBatch:
    def __init__(self, store, snapshot):
        self.store, self.snapshot = store, snapshot
        self.records = store.records(snapshot)
        self.new_records, self.files = [], {}

    def add(self, kind, payload, entity_id=None):
        record = self.store._new_record(self.snapshot, self.records, kind, payload, entity_id)
        if any(item["id"] == record["id"] for item in self.new_records):
            raise CoreError("BATCH_DUPLICATE", "One batch cannot revise the same entity twice")
        self.records[key(ref(record))] = record
        self.new_records.append(record)
        return ref(record)

    def artifact(self, raw, media_type, origin, parents=()):
        if len(raw) > 8 * 1024 * 1024:
            raise CoreError("ARTIFACT_LIMIT", "Derived artifact exceeds the core byte limit", 4)
        payload = {
            "sha256": sha(raw),
            "size": len(raw),
            "media_type": media_type,
            "origin": origin,
            "parent_refs": list(parents),
            "processing_kind": "algorithm",
        }
        for record in self.records.values():
            if record["kind"] == "artifact" and record["payload"] == payload:
                return ref(record)
        self.files[self.store.base + "/artifacts/sha256/" + sha(raw)] = raw
        return self.add("artifact", payload)

    def finish(self, data):
        return {**data, "_records": self.new_records}, self.files
