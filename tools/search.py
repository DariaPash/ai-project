"""Bounded real-vector/lexical/graph RRF memory over a committed local corpus."""

import re
from .contracts import digest, key, ref
from .errors import CoreError
from .graph import effective, dependency_maps
from .records import RecordBatch
from .safeio import canonical, parse_json

KINDS = {"extraction", "claim", "question", "option", "strategy", "promise", "experiment", "decision", "obligation"}
CHUNK_CHARS = 1400
CHUNK_OVERLAP = 160
MAX_CHUNKS = 128


def text_chunks(documents):
    """Cover complete documents with character offsets; fail, never silently truncate."""
    chunks = []
    for document in documents:
        text = document["text"]
        for start in range(0, len(text), CHUNK_CHARS - CHUNK_OVERLAP):
            end = min(start + CHUNK_CHARS, len(text))
            chunks.append({"ref": document["ref"], "start_char": start, "end_char": end, "text": text[start:end]})
            if len(chunks) > MAX_CHUNKS:
                raise CoreError(
                    "INDEX_LIMIT", "Corpus exceeds128 chunks; narrow corpus explicitly; no partial results", 4
                )
            if end == len(text):
                break
    return chunks


def corpus(snapshot, records):
    documents = []
    for r in records.values():
        if r["kind"] not in KINDS or snapshot["active"].get(r["id"]) != r["revision"]:
            continue
        p = r["payload"]
        text = p.get("text")
        if not isinstance(text, str):
            text = canonical(p).decode()
        documents.append({"ref": ref(r), "sha256": digest(r), "text": text})
    documents.sort(key=lambda d: key(d["ref"]))
    return documents, digest(
        {
            "documents": documents,
            "chunker": {"version": 2, "chars": CHUNK_CHARS, "overlap": CHUNK_OVERLAP, "max_chunks": MAX_CHUNKS},
        }
    )


def build(store, spec, expected):
    if spec != {"mode": "hybrid", "language": "eng"}:
        raise CoreError("INDEX_SPEC", "Supported spec is mode=hybrid, language=eng, installed local Apple model only")
    from .adapters.embeddings import execute

    def builder(snapshot):
        batch = RecordBatch(store, snapshot)
        documents, fingerprint = corpus(snapshot, batch.records)
        chunks = text_chunks([d for d in documents if effective(snapshot, batch.records, d["ref"])["eligible"]])
        if not chunks:
            raise CoreError("INDEX_EMPTY", "No eligible text to index", 3)
        vectors = execute([c["text"] for c in chunks])
        for chunk, vector in zip(chunks, vectors["vectors"]):
            chunk["vector"] = vector
        model = vectors["model"] + "@" + str(vectors["revision"])
        data = {
            "format": 1,
            "chunks": chunks,
            "dimension": vectors["dimension"],
            "model": model,
            "corpus_fingerprint": fingerprint,
            "rrf_k": 60,
            "network_used": False,
        }
        artifact = batch.artifact(
            canonical(data), "application/json", "model_simulation", [d["ref"] for d in documents]
        )
        saved = batch.add(
            "memory_index",
            {
                "contract_version": 6,
                "artifact_ref": artifact,
                "corpus_fingerprint": fingerprint,
                "model": model,
                "dimension": vectors["dimension"],
                "chunk_count": len(chunks),
                "indexed_snapshot_revision": snapshot["case_revision"],
                "basis_refs": [d["ref"] for d in documents],
            },
        )
        return batch.finish(
            {
                "index_ref": saved,
                "chunks": len(chunks),
                "model": model,
                "dimension": vectors["dimension"],
                "network_used": False,
                "limitations": [
                    "English local model; multilingual quality not established",
                    "No benchmark/quality thresholds measured by user instruction",
                ],
            }
        )

    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    _, fingerprint = corpus(snapshot, records)
    return store._mutate(
        "index:build", {"spec": spec, "corpus": fingerprint, "implementation": "apple-nl-english-v1"}, expected, builder
    )


def retrieve(store, query, mode="lexical", history=False):
    if not isinstance(query, str) or not query.strip() or len(query) > 1600:
        raise CoreError("QUERY", "Query must be nonempty and <=1600 chars")
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    documents, fingerprint = corpus(snapshot, records)
    if mode == "hybrid":
        indexes = [
            r
            for r in records.values()
            if r["kind"] == "memory_index" and snapshot["active"].get(r["id"]) == r["revision"]
        ]
        if not indexes:
            raise CoreError(
                "INDEX_REQUIRED", "Build a real local hybrid index first; lexical mode is available explicitly", 3
            )
        index = max(indexes, key=lambda r: int(r["id"].split("-")[1]))
        p = index["payload"]
        if p["corpus_fingerprint"] != fingerprint:
            raise CoreError("INDEX_STALE", "Indexed corpus changed; rebuild before hybrid retrieval", 3)
        data = parse_json(store.blob(records[key(p["artifact_ref"])]["payload"]["sha256"]))
        chunks = data["chunks"]
        from .adapters.embeddings import execute

        result = execute([query])
        model = result["model"] + "@" + str(result["revision"])
        if model != p["model"] or result["dimension"] != p["dimension"]:
            raise CoreError("INDEX_MODEL_CHANGED", "Local model revision/dimension changed; rebuild", 3)
        vector = result["vectors"][0]
        semantic = sorted(range(len(chunks)), key=lambda i: -sum(a * b for a, b in zip(vector, chunks[i]["vector"])))
    elif mode == "lexical":
        chunks = text_chunks(documents)
        semantic = []
    else:
        raise CoreError("RETRIEVE_MODE", "Choose lexical or hybrid explicitly")
    terms = set(re.findall(r"\w+", query.casefold()))
    scores = {i: len(terms & set(re.findall(r"\w+", c["text"].casefold()))) for i, c in enumerate(chunks)}
    lexical = sorted((i for i in scores if scores[i]), key=lambda i: (-scores[i], i))
    rankings = [lexical]
    if mode == "hybrid":
        rankings.append(semantic)
        forward, reverse = dependency_maps(records)
        seeds = {key(chunks[i]["ref"]) for i in (lexical[:3] + semantic[:3])}
        neighbors = set().union(*(forward.get(x, set()) | reverse.get(x, set()) for x in seeds)) if seeds else set()
        rankings.append([i for i, c in enumerate(chunks) if key(c["ref"]) in neighbors])
    fused = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            fused[i] = fused.get(i, 0) + 1 / (60 + rank)
    hits = []
    filtered = 0
    for i in sorted(fused, key=lambda i: (-fused[i], i)):
        c = chunks[i]
        status = effective(snapshot, records, c["ref"])
        access_denied = any("source_unavailable_or_denied" in reason for reason in status["reasons"])
        if not status["eligible"] and (not history or access_denied):
            filtered += 1
            continue
        hits.append(
            {k: v for k, v in c.items() if k != "vector"}
            | {
                "score": fused[i],
                "effective": status,
                "history_only": not status["eligible"],
                "lineage_roots": records[key(c["ref"])]["lineage_roots"],
            }
        )
        if len(hits) >= 8:
            break
    return {
        "case_revision": snapshot["case_revision"],
        "data": {
            "mode": mode,
            "hits": hits,
            "filtered_current_ineligible": filtered,
            "corpus_fingerprint": fingerprint,
            "network_used": False,
            "semantic_vectors_used": mode == "hybrid",
            "chunk_count": len(chunks),
            "chunk_char_limit": CHUNK_CHARS,
            "coordinate_system": "Unicode characters, zero-based [start_char,end_char)",
            "meaning": "Ranked local memory, not independent source support or proven answer correctness",
        },
    }
