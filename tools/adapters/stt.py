"""Strictly local Apple Speech fallback. Never prompts/downloads or uses cloud."""

from importlib.resources import files
import json
import wave
from .base import executable, run, profile
from ..errors import CoreError


def runtime_configured():
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / ".local/speech-runtime.json").exists()


def execute(request, stage):
    path = stage / "input.wav"
    path.write_bytes(request.raw)
    try:
        with wave.open(str(path), "rb") as audio:
            duration = round(audio.getnframes() * 1000 / audio.getframerate())
            if (
                audio.getcomptype() != "NONE"
                or audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
            ):
                raise CoreError("WAV_FORMAT", "STT accepts PCM16 mono 16kHz WAV only")
    except (wave.Error, EOFError) as error:
        raise CoreError("WAV_INVALID", "Audio input is not a supported WAV") from error
    if duration > request.spec["limits"]["max_duration_ms"]:
        raise CoreError("DURATION_LIMIT", "Audio duration exceeds cap", 4)
    if runtime_configured():
        from .stt_whisper import execute as local_transcription

        return local_transcription(request, stage, duration)
    if request.spec["options"].get("language", "eng") != "eng":
        raise CoreError("STT_LANGUAGE", "This local on-device adapter currently supports en_US only", 3)
    script = stage / "apple_stt.swift"
    script.write_bytes(files("tools.adapters").joinpath("apple_stt.swift").read_bytes())
    raw = run(
        [executable("swift"), "-module-cache-path", str(stage / "module-cache"), str(script), str(path)],
        request.deadline,
    )
    result = json.loads(raw)
    if result["status"] == "unavailable":
        raise CoreError("STT_AUTH_REQUIRED", result["reason"], 3)
    if result["status"] != "ok":
        raise CoreError("STT_UNAVAILABLE", "No final local recognition output was produced", 3)
    segments = []
    for item in result["segments"]:
        if not 0 <= item["start_ms"] <= item["end_ms"] <= duration + 500:
            raise CoreError("STT_TIMECODE", "Recognizer returned invalid time bounds")
        segments.append(
            {
                "kind": "audio",
                "coordinates": {"start_ms": item["start_ms"], "end_ms": item["end_ms"], "speaker": "unknown"},
                "text": item["text"],
                "confidence": item["confidence"] * 100,
                "uncertain": True,  # No listening verification, irrespective of vocabulary/confidence.
            }
        )
    if not segments:
        raise CoreError("STT_NO_SPEECH", "No speech recognized; no transcript is invented", 3)
    return {
        "status": "partial",
        "engine": profile("swift"),
        "segments": segments,
        "coverage": {
            "duration_ms": duration,
            "on_device_required": True,
            "speaker_identity": "unknown",
            "listening_verification": "not_performed",
        },
        "children": [],
        "limitations": [
            "On-device transcription, no cloud fallback or automatic authorization request",
            "Critical words/numbers and low confidence remain uncertain; no diarization/person identity claim",
        ],
    }
