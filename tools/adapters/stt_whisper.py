"""Pinned project-local whisper.cpp, no network or cloud during transcription."""

from pathlib import Path

from .base import bounded_read, run
from ..errors import CoreError
from ..safeio import parse_json


ROOT = Path(__file__).resolve().parents[2]


def runtime():
    from ..diagnostics import speech_runtime

    try:
        return speech_runtime(ROOT)
    except FileNotFoundError as error:
        raise CoreError("STT_UNAVAILABLE", "Run the approved project-local speech setup first", 3) from error


def execute(request, stage, duration):
    config = runtime()
    prefix = stage / "transcript"
    output = prefix.with_suffix(".json")
    cap = min(request.spec["limits"]["max_output_bytes"], 1024 * 1024)
    args = [
        "/usr/bin/sandbox-exec",
        "-p",
        "(version 1)(allow default)(deny network*)",
        str(ROOT / config["executable"]),
        "--model",
        str(ROOT / config["model"]),
        "--file",
        str(stage / "input.wav"),
        "--language",
        {"eng": "en", "rus": "ru"}[request.spec["options"].get("language", "eng")],
        "--threads",
        "4",
        "--best-of",
        "1",
        "--beam-size",
        "1",
        "--no-gpu",
        "--no-fallback",
        "--output-json-full",
        "--output-file",
        str(prefix),
    ]
    run(args, request.deadline, cap=cap, file_cap=cap, output_files=(output,))
    data = parse_json(bounded_read(output, cap))
    segments = []
    for item in data.get("transcription", []):
        text = item.get("text", "").strip()
        if not text:
            continue
        begin, end = item["offsets"]["from"], item["offsets"]["to"]
        if type(begin) is not int or type(end) is not int or not 0 <= begin <= end <= duration + 500:
            raise CoreError("STT_TIMECODE", "Recognizer returned invalid audio bounds")
        segments.append(
            {
                "kind": "audio",
                "coordinates": {"start_ms": min(begin, duration), "end_ms": min(end, duration), "speaker": "unknown"},
                "text": text,
                "confidence": None,
                "uncertain": True,
            }
        )
    if not segments:
        raise CoreError("STT_NO_SPEECH", "No speech recognized; no transcript invented", 3)
    return {
        "status": "partial",
        "engine": {k: v for k, v in config.items() if k not in {"executable", "model", "approval_receipt"}},
        "segments": segments,
        "children": [],
        "coverage": {
            "duration_ms": duration,
            "on_device_required": True,
            "network_used": False,
            "speaker_identity": "unknown",
            "listening_verification": "not_performed",
        },
        "limitations": [
            "Actual local whisper.cpp transcription under network denial; no cloud or recognition-time downloads",
            "Numbers and negations remain uncertain without listening verification; no speaker identity or diarization",
            "Base model, greedy decoding; multilingual accuracy not established by a benchmark",
        ],
    }
