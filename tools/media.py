"""Media dispatch, schema validation and transactional attachment to source v1."""

import base64
from importlib.resources import files
import os
import subprocess
import sys
import tempfile
import signal
from pathlib import Path
from .contracts import digest, key, sha, validate_schema
from .errors import CoreError
from .safeio import canonical, parse_json

FORMATS = {"image", "scan_pdf", "audio", "video"}


def profile(format_name):
    from .adapters.base import profile as engine_profile

    names = (
        ["tesseract"]
        if format_name == "image"
        else ["tesseract", "pdftoppm"]
        if format_name == "scan_pdf"
        else ["swift"]
        if format_name == "audio"
        else ["ffmpeg", "ffprobe"]
    )
    modules = ["base.py", "ocr.py", "stt.py", "stt_whisper.py", "video.py", "apple_stt.swift"]
    installed_speech = None
    if format_name == "audio" and (Path(__file__).resolve().parents[1] / ".local/speech-runtime.json").exists():
        from .adapters.stt_whisper import runtime

        speech = runtime()
        installed_speech = {k: v for k, v in speech.items() if k not in {"executable", "model", "approval_receipt"}}
    return {
        "implementation": "step04-local-media-v1",
        "engines": [installed_speech] if installed_speech else [engine_profile(name) for name in names],
        "implementation_sha256": digest(
            {name: sha(files("tools.adapters").joinpath(name).read_bytes()) for name in modules}
            | {
                name: sha(files("tools").joinpath(name).read_bytes())
                for name in ("media.py", "media_worker.py", "sources.py")
            }
        ),
        "python": sys.version.split()[0],
    }


def parse(raw, spec):
    validate_schema("media-spec", spec)
    base = Path(tempfile.gettempdir()).resolve()
    approved = base / "opencode"
    if approved.is_dir() and not approved.is_symlink():
        base = approved
    process = subprocess.Popen(
        [sys.executable, "-m", "tools.media_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(base),
        },
    )
    try:
        output, _ = process.communicate(
            canonical({"raw_base64": base64.b64encode(raw).decode(), "spec": spec}),
            timeout=spec["limits"]["timeout_ms"] / 1000 + 1,
        )
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise CoreError("MEDIA_TIMEOUT", "Media worker exceeded deadline; no automatic retry", 5) from error
    finally:
        # Also reap groups whose leader already exited, not only live leaders.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if not output or len(output) > spec["limits"]["max_output_bytes"] + 4096:
        raise CoreError("MEDIA_OUTPUT_LIMIT", "Missing or oversized media worker response", 4)
    response = parse_json(output)
    if not response["ok"]:
        raise CoreError(response["code"], response["reason"], response["exit"])
    media = response["data"]
    fragments = [{k: s[k] for k in ("kind", "coordinates", "text")} for s in media["segments"]]
    return {
        "text": "\n".join(s["text"] for s in media["segments"]),
        "fragments": fragments,
        "tables": {},
        "warnings": media["limitations"],
        "coverage": {},
        "_media": media,
    }


def attach(batch, source_ref, media, spec):
    result = {k: v for k, v in media.items() if k != "children"}
    result["children"] = []
    for child in media["children"]:
        raw = base64.b64decode(child["raw_base64"], validate=True)
        if sha(raw) != child["sha256"]:
            raise CoreError("MEDIA_CHILD_HASH", "Derived child hash differs from its receipt")
        reference = batch.artifact(raw, child["media_type"], spec["origin"], [source_ref])
        result["children"].append(
            {k: child[k] for k in ("sha256", "media_type", "mapping")} | {"artifact_ref": reference}
        )
    validate_schema("media-extraction", result)
    return result


def _validate_locations(media, source, blob_reader):
    """Validate physical coordinates against immutable bytes, not just fragment equality."""
    from fractions import Fraction
    from io import BytesIO
    import wave
    from .adapters.ocr import png_dimensions

    def require(condition):
        if not condition:
            raise CoreError("MEDIA_LOCATOR", "Media coordinates/mappings disagree with physical source or child", 2)

    def integer(value, low=0, high=None):
        return type(value) is int and value >= low and (high is None or value <= high)

    coverage = media["coverage"]
    children = media["children"]
    format_name = media["format"]
    require(format_name == source["payload"]["format"])
    duration = coverage.get("duration_ms")
    if format_name in {"audio", "video"}:
        require(integer(duration, 1, 120000))
    dimensions = None
    if format_name == "image":
        dimensions = png_dimensions(blob_reader(source["payload"]["sha256"]), 4194304)
        require(coverage.get("dimensions") == dict(zip(("width", "height"), dimensions)))
        require(not children and coverage.get("physical_pages") is None)
    elif format_name == "scan_pdf":
        from pypdf import PdfReader

        count = len(PdfReader(BytesIO(blob_reader(source["payload"]["sha256"])), strict=True).pages)
        require(coverage.get("physical_pages") == count)
        pages = coverage.get("processed_pages", [])
        require(bool(pages) and len(set(pages)) == len(pages) and all(integer(n, 1, count) for n in pages))
        require(coverage.get("unprocessed_pages") == [n for n in range(1, count + 1) if n not in pages])
        require(len(children) == len(pages))
        require([c["mapping"].get("physical_page") for c in children] == pages)
    elif format_name == "audio":
        with wave.open(BytesIO(blob_reader(source["payload"]["sha256"])), "rb") as audio:
            require(duration == round(audio.getnframes() * 1000 / audio.getframerate()))
        require(not children and coverage.get("listening_verification") == "not_performed")
    elif format_name == "video":
        require(integer(coverage.get("width"), 1) and integer(coverage.get("height"), 1))
        require(coverage["width"] * coverage["height"] <= 4194304)
        require(integer(coverage.get("frame_count"), 1))
        fps = Fraction(coverage.get("fps", "0"))
        require(0 < fps <= 120)
        require(abs(round(float(Fraction(coverage["frame_count"], 1) / fps) * 1000) - duration) <= 1)
        require(coverage.get("visual_analysis_performed") is False and coverage.get("full_visual_coverage") is False)
        require(coverage.get("audio_transcription_performed") is False)
        require(coverage.get("mode") in {"audio_only", "sampled_frames", "dense_episode"})
        require(bool(children) and len(children) <= 64)
        require(
            coverage.get("observed_timestamps_ms")
            == [c["mapping"]["timestamp_ms"] for c in children if "timestamp_ms" in c["mapping"]]
        )
        require(len(media["segments"]) == len(children))
    for child in children:
        mapping = child["mapping"]
        if child["media_type"] == "image/png":
            size = png_dimensions(blob_reader(child["sha256"]), 4194304)
            require(size == (mapping.get("width"), mapping.get("height")))
            if format_name == "scan_pdf":
                require(integer(mapping.get("physical_page"), 1, coverage["physical_pages"]))
                require(integer(mapping.get("dpi"), 72, 144))
            else:
                require(format_name == "video" and coverage["mode"] != "audio_only")
                require(size == (coverage["width"], coverage["height"]))
                require(integer(mapping.get("requested_ms"), 0, duration))
                require(integer(mapping.get("timestamp_ms"), 0, duration - 1))
                require(integer(mapping.get("frame_index"), 0, coverage["frame_count"] - 1))
                require(mapping["timestamp_ms"] == round(float(Fraction(mapping["frame_index"], 1) / fps) * 1000))
                require(mapping.get("offset_ms") == mapping["timestamp_ms"] - mapping["requested_ms"])
                require(
                    mapping["frame_index"]
                    == min(coverage["frame_count"] - 1, int(round(Fraction(mapping["requested_ms"], 1000) * fps)))
                )
        elif child["media_type"] == "audio/wav":
            require(format_name == "video" and coverage["mode"] == "audio_only" and len(children) == 1)
            require(integer(mapping.get("source_start_ms"), 0, duration - 1) and mapping.get("child_start_ms") == 0)
            with wave.open(BytesIO(blob_reader(child["sha256"])), "rb") as audio:
                require(mapping.get("duration_ms") == round(audio.getnframes() * 1000 / audio.getframerate()))
            require(integer(mapping.get("duration_ms"), 1, duration - mapping["source_start_ms"]))
        else:
            require(False)
    seen = set()
    for segment in media["segments"]:
        c = segment["coordinates"]
        # No current adapter provides separate listening/visual sample verification.
        require(segment["uncertain"] is True)
        if segment["kind"] == "image":
            require(format_name in {"image", "scan_pdf"})
            if format_name == "scan_pdf":
                matches = [child for child in children if child["mapping"]["physical_page"] == c.get("physical_page")]
                require(len(matches) == 1)
                dimensions = (matches[0]["mapping"]["width"], matches[0]["mapping"]["height"])
            else:
                require("physical_page" not in c)
            require((c.get("width"), c.get("height")) == dimensions and c.get("orientation") == "top_left_pixels")
            box = c.get("bbox", [])
            require(len(box) == 4 and all(integer(v) for v in box))
            x, y, w, h = box
            require(w > 0 and h > 0 and x + w <= dimensions[0] and y + h <= dimensions[1])
        elif segment["kind"] == "audio":
            require(format_name in {"audio", "video"})
            require(integer(c.get("start_ms"), 0, duration) and integer(c.get("end_ms"), 0, duration))
            require(c["start_ms"] <= c["end_ms"] and c.get("speaker") == "unknown")
            if format_name == "video":
                require(coverage["mode"] == "audio_only")
                mapping = children[0]["mapping"]
                require(
                    c["start_ms"] == mapping["source_start_ms"]
                    and c["end_ms"] == c["start_ms"] + mapping["duration_ms"]
                )
        elif segment["kind"] == "video":
            require(format_name == "video" and coverage["mode"] != "audio_only")
            require(
                integer(c.get("timestamp_ms"), 0, duration - 1)
                and integer(c.get("frame_index"), 0, coverage["frame_count"] - 1)
            )
            matches = [
                child
                for child in children
                if child["sha256"] == c.get("frame_sha256")
                and child["mapping"].get("timestamp_ms") == c["timestamp_ms"]
                and child["mapping"].get("frame_index") == c["frame_index"]
            ]
            require(len(matches) == 1 and c["frame_index"] not in seen)
            seen.add(c["frame_index"])
        else:
            require(False)


def validate_record(record, records, blob_reader):
    from .adapters.ocr import png_dimensions

    p = record["payload"]
    kind = record["kind"]
    if kind == "extraction" and "media" in p.get("coverage", {}):
        media = p["coverage"]["media"]
        validate_schema("media-extraction", media)
        for child in media["children"]:
            artifact = records[key(child["artifact_ref"])]
            if (
                artifact["kind"] != "artifact"
                or artifact["payload"]["sha256"] != child["sha256"]
                or artifact["payload"]["media_type"] != child["media_type"]
                or p["source_ref"] not in artifact["payload"]["parent_refs"]
            ):
                raise CoreError("MEDIA_CHILD_REF", "Child must be the exact artifact derived from the source")
        if p["fragments"] != [{k: s[k] for k in ("kind", "coordinates", "text")} for s in media["segments"]]:
            raise CoreError("MEDIA_SEGMENTS", "Media segments and source locators disagree")
        try:
            _validate_locations(media, records[key(p["source_ref"])], blob_reader)
        except CoreError:
            raise
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            raise CoreError("MEDIA_LOCATOR", "Malformed media coordinates or coverage", 2) from error
    if kind == "ux_observation":
        source = records[key(p["source_ref"])]
        artifact = records[key(p["artifact_ref"])]
        if (
            source["kind"] != "source"
            or artifact["kind"] != "artifact"
            or artifact["payload"]["sha256"] != p["artifact_sha256"]
        ):
            raise CoreError("UX_REF", "UX must identify exact source and image artifact")
        width, height = png_dimensions(blob_reader(p["artifact_sha256"]), 4194304)
        if (width, height) != (p["width"], p["height"]):
            raise CoreError("UX_DIMENSIONS", "Declared UX dimensions differ from the image")
        x, y, w, h = p["bbox"]
        if not w or not h or x + w > width or y + h > height:
            raise CoreError("UX_BBOX", "UX region is outside the image")
        if source["payload"]["sha256"] != p["artifact_sha256"]:
            candidates = [
                c
                for e in records.values()
                if e["kind"] == "extraction" and e["payload"]["source_ref"] == p["source_ref"]
                for c in e["payload"].get("coverage", {}).get("media", {}).get("children", [])
                if c["artifact_ref"] == p["artifact_ref"]
            ]
            if not candidates or (
                "timestamp_ms" in p
                and not any(c["mapping"].get("timestamp_ms") == p["timestamp_ms"] for c in candidates)
            ):
                raise CoreError("UX_SOURCE", "Frame/image must be a located derivative of the declared source")
    if kind == "ux_journey":
        if any(records[key(step["observation_ref"])]["kind"] != "ux_observation" for step in p["steps"]):
            raise CoreError("UX_STEP", "Journey steps require UX observation refs")
