"""MP4/CFR-only bounded frame/audio extraction, no implied visual analysis."""

import json
from io import BytesIO
import wave
from fractions import Fraction
from pathlib import Path

from .base import executable, run, profile, bounded_read
from .ocr import png_dimensions
from ..contracts import sha
from ..errors import CoreError


def execute(request, stage):
    raw = request.raw
    spec = request.spec
    limits = spec["limits"]
    options = spec["options"]
    if len(raw) < 16 or raw[4:8] != b"ftyp":
        raise CoreError("VIDEO_CONTAINER", "Only bounded local MP4/ftyp input is supported; no playlists", 4)
    path = stage / "input.mp4"
    path.write_bytes(raw)
    safe = ["-protocol_whitelist", "file,pipe", "-enable_drefs", "0", "-use_absolute_path", "0", "-f", "mov"]
    metadata = json.loads(
        run(
            [executable("ffprobe"), "-v", "error", *safe, "-show_streams", "-show_format", "-of", "json", str(path)],
            request.deadline,
        )
    )
    streams = metadata.get("streams", [])
    videos = [s for s in streams if s["codec_type"] == "video"]
    if len(videos) != 1:
        raise CoreError("VIDEO_STREAM", "Exactly one video stream is required")
    video = videos[0]
    width, height = int(video["width"]), int(video["height"])
    if width * height > limits["max_pixels"]:
        raise CoreError("PIXEL_LIMIT", "Video frame dimensions exceed cap", 4)
    duration = round(float(metadata["format"]["duration"]) * 1000)
    if duration <= 0 or duration > limits["max_duration_ms"]:
        raise CoreError("DURATION_LIMIT", "Video duration exceeds cap", 4)
    fps = Fraction(video["avg_frame_rate"])
    if (
        fps <= 0
        or fps > 120
        or fps != Fraction(video["r_frame_rate"])
        or abs(float(video.get("start_time", 0))) > 0.001
    ):
        raise CoreError("VIDEO_TIMING", "Only zero-start constant-frame-rate inputs are supported", 3)
    count = int(video.get("nb_frames", 0))
    if count <= 0:
        raise CoreError("VIDEO_TIMING", "Frame count is unavailable; exact timestamp mapping cannot be claimed", 3)
    # Declared average/rate equality is not CFR proof: composition offsets can
    # move individual presented frames while leaving both rates unchanged.
    timing = json.loads(
        run(
            [
                executable("ffprobe"),
                "-v",
                "error",
                *safe,
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(path),
            ],
            request.deadline,
        )
    )
    frames = timing.get("frames", [])
    if len(frames) != count or any(
        "best_effort_timestamp_time" not in frame
        or abs(Fraction(frame["best_effort_timestamp_time"]) - Fraction(index, 1) / fps) > Fraction(1, 1000000)
        for index, frame in enumerate(frames)
    ):
        raise CoreError(
            "VIDEO_TIMING",
            "Actual presentation timestamps are not supported zero-start CFR; no inferred frame mapping",
            3,
        )
    mode = options.get("mode")
    children = []
    segments = []
    remaining = limits["max_output_bytes"]
    if mode == "audio_only":
        audio_streams = [s for s in streams if s["codec_type"] == "audio"]
        if not audio_streams:
            raise CoreError("VIDEO_NO_AUDIO", "Video has no audio stream", 3)
        track = audio_streams[0]
        if "start_time" not in track or "duration" not in track:
            raise CoreError("VIDEO_AUDIO_TIMING", "Audio timing is unavailable; no inferred alignment", 3)
        source_start = round(float(track["start_time"]) * 1000)
        track_duration = round(float(track["duration"]) * 1000)
        if source_start != 0 or track_duration <= 0 or track_duration > duration:
            raise CoreError(
                "VIDEO_AUDIO_TIMING",
                "Only zero-start bounded audio is supported; delayed audio is explicitly unavailable",
                3,
            )
        # PCM16 mono16k plus container header: fail before any write if too small.
        if track_duration * 32 + 128 > remaining:
            raise CoreError("MEDIA_OUTPUT_LIMIT", "PCM derivative cannot fit output budget", 4)
        output = stage / "audio.wav"
        run(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                *safe,
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            request.deadline,
            file_cap=remaining,
            output_files=(output,),
        )
        content = bounded_read(output, remaining)
        with wave.open(BytesIO(content), "rb") as audio:
            child_duration = round(audio.getnframes() * 1000 / audio.getframerate())
        if child_duration <= 0 or abs(child_duration - track_duration) > 100 or child_duration > duration:
            raise CoreError("VIDEO_AUDIO_TIMING", "Decoded track duration differs from supported source mapping", 3)
        children = [
            {
                "raw": content,
                "media_type": "audio/wav",
                "mapping": {"source_start_ms": source_start, "child_start_ms": 0, "duration_ms": child_duration},
            }
        ]
        text = "Audio track extracted; speech and visual content have not been analyzed."
        segments = [
            {
                "kind": "audio",
                "coordinates": {
                    "start_ms": source_start,
                    "end_ms": source_start + child_duration,
                    "speaker": "unknown",
                },
                "text": text,
                "uncertain": True,
                "confidence": None,
            }
        ]
    elif mode in {"sampled_frames", "dense_episode"}:
        if mode == "sampled_frames":
            times = options.get("timestamps_ms")
        else:
            start, end, interval = (options.get(k) for k in ("start_ms", "end_ms", "frame_interval_ms"))
            if None in (start, end, interval) or not 0 <= start < end <= duration:
                raise CoreError("VIDEO_EPISODE", "Dense episode requires valid explicit start/end/interval")
            times = list(range(start, end + 1, interval))
        if (
            not times
            or len(times) > limits["max_frames"]
            or times != sorted(times)
            or any(t < 0 or t > duration for t in times)
        ):
            raise CoreError("FRAME_LIMIT", "Invalid/unsorted timestamps or too many frames", 4)
        seen = set()
        for requested in times:
            index = min(count - 1, int(round(Fraction(requested, 1000) * fps)))
            if index in seen:
                continue
            seen.add(index)
            actual = round(float(Fraction(index, 1) / fps) * 1000)
            output = stage / f"frame-{index}.png"
            run(
                [
                    executable("ffmpeg"),
                    "-v",
                    "error",
                    "-nostdin",
                    *safe,
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-vf",
                    f"select=eq(n\\,{index})",
                    "-fps_mode",
                    "vfr",
                    "-frames:v",
                    "1",
                    str(output),
                ],
                request.deadline,
                file_cap=remaining,
                output_files=(output,),
            )
            content = bounded_read(output, remaining)
            remaining -= len(content)
            w, h = png_dimensions(content, limits["max_pixels"])
            mapping = {
                "requested_ms": requested,
                "timestamp_ms": actual,
                "offset_ms": actual - requested,
                "frame_index": index,
                "width": w,
                "height": h,
            }
            children.append({"raw": content, "media_type": "image/png", "mapping": mapping})
            segments.append(
                {
                    "kind": "video",
                    "coordinates": {"timestamp_ms": actual, "frame_index": index, "frame_sha256": sha(content)},
                    "text": f"Extracted frame at {actual} ms; visual interpretation not performed by FFmpeg.",
                    "uncertain": True,
                    "confidence": None,
                }
            )
            if sum(len(c["raw"]) for c in children) > limits["max_output_bytes"]:
                raise CoreError("MEDIA_OUTPUT_LIMIT", "Derived frames exceed aggregate cap", 4)
    else:
        raise CoreError("VIDEO_MODE", "Choose audio_only, sampled_frames or dense_episode explicitly")
    return {
        "status": "partial",
        "engine": profile("ffmpeg"),
        "segments": segments,
        "children": children,
        "coverage": {
            "mode": mode,
            "duration_ms": duration,
            "width": width,
            "height": height,
            "fps": str(fps),
            "frame_count": count,
            "timing_verification": "all_decoded_frame_pts_match_cfr_within_1us",
            "visual_analysis_performed": False,
            "full_visual_coverage": False,
            "observed_timestamps_ms": [
                c["mapping"]["timestamp_ms"] for c in children if "timestamp_ms" in c["mapping"]
            ],
            "audio_transcription_performed": False,
        },
        "limitations": [
            "Extraction is not visual understanding; sparse gaps and between-frame events remain unknown",
            "MP4 constant-frame-rate only; no network protocols, playlists or enabled external data references",
        ],
    }
