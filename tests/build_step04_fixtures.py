"""Owned bitmap/scan/video fixtures; explicit oracle fixed before processing.

No OCR/STT output is used as expected data. No network, package/model downloads.
"""

import json
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from tools.contracts import sha
from tools.development import ROOT, now, write_json

FONT = {
    "A": [14, 17, 17, 31, 17, 17, 17],
    "B": [30, 17, 17, 30, 17, 17, 30],
    "C": [14, 17, 16, 16, 16, 17, 14],
    "D": [30, 17, 17, 17, 17, 17, 30],
    "E": [31, 16, 16, 30, 16, 16, 31],
    "F": [31, 16, 16, 30, 16, 16, 16],
    "G": [14, 17, 16, 23, 17, 17, 15],
    "H": [17, 17, 17, 31, 17, 17, 17],
    "I": [14, 4, 4, 4, 4, 4, 14],
    "J": [7, 2, 2, 2, 18, 18, 12],
    "K": [17, 18, 20, 24, 20, 18, 17],
    "L": [16, 16, 16, 16, 16, 16, 31],
    "M": [17, 27, 21, 21, 17, 17, 17],
    "N": [17, 25, 21, 19, 17, 17, 17],
    "O": [14, 17, 17, 17, 17, 17, 14],
    "P": [30, 17, 17, 30, 16, 16, 16],
    "Q": [14, 17, 17, 17, 21, 18, 13],
    "R": [30, 17, 17, 30, 20, 18, 17],
    "S": [15, 16, 16, 14, 1, 1, 30],
    "T": [31, 4, 4, 4, 4, 4, 4],
    "U": [17, 17, 17, 17, 17, 17, 14],
    "V": [17, 17, 17, 17, 17, 10, 4],
    "W": [17, 17, 17, 21, 21, 21, 10],
    "X": [17, 17, 10, 4, 10, 17, 17],
    "Y": [17, 17, 10, 4, 4, 4, 4],
    "Z": [31, 1, 2, 4, 8, 16, 31],
    "0": [14, 17, 19, 21, 25, 17, 14],
    "1": [4, 12, 4, 4, 4, 4, 14],
    "2": [14, 17, 1, 2, 4, 8, 31],
    "3": [30, 1, 1, 14, 1, 1, 30],
    "4": [2, 6, 10, 18, 31, 2, 2],
    "5": [31, 16, 16, 30, 1, 1, 30],
    "6": [14, 16, 16, 30, 17, 17, 14],
    "7": [31, 1, 2, 4, 8, 8, 8],
    "8": [14, 17, 17, 14, 17, 17, 14],
    "9": [14, 17, 17, 15, 1, 1, 14],
    "%": [25, 25, 2, 4, 8, 19, 19],
    ".": [0, 0, 0, 0, 0, 12, 12],
    " ": [0] * 7,
    "-": [0, 0, 0, 31, 0, 0, 0],
    ":": [0, 4, 4, 0, 4, 4, 0],
}


def bitmap():
    w, h = 960, 540
    data = bytearray(b"\xff" * (w * h * 3))

    def rect(x, y, width, height, color):
        for row in range(y, min(y + height, h)):
            for col in range(x, min(x + width, w)):
                data[(row * w + col) * 3 : (row * w + col) * 3 + 3] = bytes(color)

    def text(value, x, y, scale=4):
        for letter in value:
            for row, bits in enumerate(FONT[letter]):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        rect(x + col * scale, y + row * scale, scale, scale, (20, 20, 20))
            x += 6 * scale

    text("SYNTHETIC REVIEW DRAFT", 40, 35, 5)
    text("STEP 1 OF 3", 40, 110, 4)
    text("RETENTION 15%", 40, 170, 3)
    text("EXPORT PLANNED", 40, 230, 4)
    text("NOT AVAILABLE", 40, 280, 4)
    rect(35, 350, 220, 80, (210, 225, 245))
    text("NEXT", 70, 375, 4)
    text("COMPLETION UNKNOWN", 40, 465, 4)
    return w, h, bytes(data)


def png(w, h, rgb):
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)

    rows = b"".join(b"\0" + rgb[y * w * 3 : (y + 1) * w * 3] for y in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def scan(w, h, rgb):
    writer = PdfWriter()
    page = writer.add_blank_page(width=w, height=h)
    image = DecodedStreamObject()
    image.set_data(rgb)
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(w),
            NameObject("/Height"): NumberObject(h),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)})}
    )
    content = DecodedStreamObject()
    content.set_data(f"q {w} 0 0 {h} 0 0 cm /Im1 Do Q".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    assert "/04/" in progress["active_run"]
    folder = ROOT / "tests/fixtures/media"
    freeze = ROOT / progress["active_run"] / "fixture-freeze.json"
    if freeze.exists():
        for name, expected in json.loads(freeze.read_text())["files"].items():
            assert sha((ROOT / name).read_bytes()) == expected
        print("Frozen media inputs verified, not regenerated")
        return
    folder.mkdir(parents=True, exist_ok=True)
    w, h, rgb = bitmap()
    for name, raw in [
        ("screen.png", png(w, h, rgb)),
        ("scan.pdf", scan(w, h, rgb)),
        ("corrupt.png", b"not an image"),
        ("remote.m3u8", b"#EXTM3U\nhttps://127.0.0.1/private\n"),
    ]:
        path = folder / name
        assert not path.exists()
        path.write_bytes(raw)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Generation needs the already-installed local FFmpeg"
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        "file,pipe",
        "-loop",
        "1",
        "-framerate",
        "25",
        "-i",
        str(folder / "screen.png"),
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=12",
        "-t",
        "12",
        "-vf",
        "drawbox=x=680:y=350:w=180:h=80:color=red:t=fill:enable='gte(t,5.2)*lt(t,5.6)'",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(folder / "event.mp4"),
    ]
    process = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    # Own non-speech negative; never invent speech from a filename or oracle.
    with wave.open(str(folder / "noise.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000 * 3)
    speech_intervals = []
    with tempfile.TemporaryDirectory(
        prefix="fixture-tts-", dir="/private/var/folders/fx/qskf3zh56ns2mvx4hbb9p8gc0000gn/T/opencode"
    ) as stage:
        combined = bytearray()
        original = bytearray()
        for i, text in enumerate(
            ["This is a synthetic technical recording.", "Retention is fifteen percent.", "Do not send the recording."]
        ):
            aiff = Path(stage) / f"part-{i}.aiff"
            wav = Path(stage) / f"part-{i}.wav"
            args = [
                "/usr/bin/sandbox-exec",
                "-p",
                "(version 1)(allow default)(deny network*)",
                "/usr/bin/say",
                "-v",
                "Albert",
                "-r",
                "170",
                "-o",
                str(aiff),
                text,
            ]
            result = subprocess.run(args, capture_output=True, text=True, timeout=25, env={"PATH": os.defpath})
            assert result.returncode == 0, result.stderr
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(aiff),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0, result.stderr
            with wave.open(str(wav), "rb") as audio:
                raw = audio.readframes(audio.getnframes())
            start = len(combined) // 32
            end = start + len(raw) // 32
            speech_intervals.append(
                {
                    "start_ms": start,
                    "end_ms": end,
                    "text": text if i < 2 else None,
                    "uncertain": i == 2,
                    "authored_text_not_stt": text,
                }
            )
            original.extend(raw + b"\0\0" * 4000)
            if i == 2:
                raw = raw[: len(raw) // 6] + b"\0" * (len(raw) * 2 // 3) + raw[len(raw) * 5 // 6 :]
                raw = raw[: len(raw) // 2 * 2]
            combined.extend(raw + b"\0\0" * 4000)
        for name, raw in [("speech.wav", combined), ("speech-clear.wav", original)]:
            with wave.open(str(folder / name), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(raw)
    oracle = {
        "origin": "synthetic_fixture",
        "image": {
            "dimensions": [w, h],
            "visible": ["STEP 1 OF 3", "RETENTION 15%", "EXPORT PLANNED", "NOT AVAILABLE", "COMPLETION UNKNOWN"],
            "critical_number": "15%",
            "critical_uncertainty": True,
            "completion_observed": False,
            "button_bbox": [35, 350, 220, 80],
        },
        "scan": {"physical_pages": 1, "text_layer": False},
        "video": {
            "duration_ms": 12000,
            "sparse_ms": [0, 4000, 8000, 11960],
            "event_interval_ms": [5200, 5600],
            "dense_episode_ms": [5000, 6000],
            "dense_interval_ms": 100,
            "sparse_event_seen": False,
            "full_coverage": False,
        },
        "audio": {
            "fixture": "noise.wav",
            "contains_speech": False,
            "speech_fixture_status": "Own synthetic Albert TTS generated successfully with child network denied; STT model still unavailable",
            "speech_intervals": speech_intervals,
            "timecode_tolerance_ms": 500,
            "expected": "unavailable_or_no_speech_not_a_guessed_number",
        },
        "limitations": "Owned artificial bitmap/video/tone, not UX behavior or field recordings; no speech recognition success claimed",
    }
    write_json(folder / "oracle.json", oracle)
    manifest = {
        "schema_version": 1,
        "origin": "synthetic_fixture",
        "rights": {"processing": True, "external_transfer": False, "publication": False},
        "files": {p.name: sha(p.read_bytes()) for p in sorted(folder.iterdir()) if p.is_file()},
        "generator_sha256": sha(Path(__file__).read_bytes()),
        "tools": {
            "ffmpeg": subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        },
        "licenses": "Original bitmap/content; local FFmpeg GPL build and installed Apple Albert TTS on own text; no voice cloning/provider upload/publication rights asserted",
    }
    write_json(folder / "manifest.json", manifest)
    write_json(
        freeze,
        {
            "frozen_at": now(),
            "files": {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(folder.iterdir()) if p.is_file()},
            "oracle_method": "Explicit design coordinates/text/timeline before any OCR/STT/video adapter processing",
        },
    )
    print(
        json.dumps(
            {
                "freeze": str(freeze.relative_to(ROOT)),
                "inputs": len(manifest["files"]),
                "speech_gate": "blocked, no fake speech fixture/STT",
            }
        )
    )


if __name__ == "__main__":
    main()
