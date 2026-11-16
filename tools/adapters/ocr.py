"""Local PNG/scan OCR with exact physical-page and pixel-box coordinates."""

import csv
from io import StringIO, BytesIO
from pathlib import Path
import re
import struct
import zlib

from .base import executable, run, profile, bounded_read
from ..errors import CoreError


def png_dimensions(raw, max_pixels):
    if (
        len(raw) < 33
        or raw[:8] != b"\x89PNG\r\n\x1a\n"
        or raw[12:16] != b"IHDR"
        or struct.unpack(">I", raw[8:12])[0] != 13
    ):
        raise CoreError("PNG_INVALID", "Only PNG with a valid IHDR is supported")
    if zlib.crc32(raw[12:29]) & 0xFFFFFFFF != struct.unpack(">I", raw[29:33])[0]:
        raise CoreError("PNG_INVALID", "PNG header checksum is invalid")
    width, height = struct.unpack(">II", raw[16:24])
    if not width or not height or width * height > max_pixels:
        raise CoreError("PIXEL_LIMIT", "PNG dimensions exceed the approved pixel cap", 4)
    return width, height


def _image(path, spec, deadline, page=None):
    with path.open("rb") as stream:
        width, height = png_dimensions(stream.read(33), spec["limits"]["max_pixels"])
    language = spec["options"].get("language", "eng")
    out = run(
        [executable("tesseract"), str(path), "stdout", "-l", language, "--psm", "6", "tsv"],
        deadline,
        spec["limits"]["max_output_bytes"],
    )
    segments = []
    for row in csv.DictReader(StringIO(out.decode("utf-8")), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise CoreError("OCR_BBOX", "OCR engine returned an invalid pixel box")
        confidence = float(row["conf"])
        # Confidence cannot establish whether an arbitrary token changes meaning.
        # All raw OCR remains unverified until a separate sample-verification path.
        uncertain = True
        coords = {"bbox": [x, y, w, h], "width": width, "height": height, "orientation": "top_left_pixels"}
        if page is not None:
            coords["physical_page"] = page
        segments.append(
            {"kind": "image", "coordinates": coords, "text": text, "uncertain": uncertain, "confidence": confidence}
        )
    return segments, {"width": width, "height": height}


def execute(request, stage):
    from pypdf import PdfReader

    spec = request.spec
    children = []
    segments = []
    pages = []
    remaining = spec["limits"]["max_output_bytes"]
    if spec["format"] == "image":
        path = stage / "input.png"
        path.write_bytes(request.raw)
        segments, dimensions = _image(path, spec, request.deadline)
        coverage = {"dimensions": dimensions, "physical_pages": None, "ocr_used": True}
    else:
        reader = PdfReader(BytesIO(request.raw), strict=True)
        if reader.is_encrypted:
            raise CoreError("PDF_ENCRYPTED", "Encrypted scan is unavailable", 3)
        if len(reader.pages) > spec["limits"]["max_pages"]:
            raise CoreError("PAGES_LIMIT", "Scan page count exceeds cap", 4)
        chosen = spec["options"].get("pages", list(range(1, len(reader.pages) + 1)))
        if not chosen or len(chosen) > spec["limits"]["max_pages"] or max(chosen) > len(reader.pages):
            raise CoreError("PAGE_RANGE", "Requested physical page is outside the scan")
        path = stage / "input.pdf"
        path.write_bytes(request.raw)
        dpi = spec["options"].get("dpi", 72)
        for number in chosen:
            page = reader.pages[number - 1]
            w = float(page.mediabox.width) * dpi / 72
            h = float(page.mediabox.height) * dpi / 72
            if w <= 0 or h <= 0 or w * h > spec["limits"]["max_pixels"]:
                raise CoreError("PIXEL_LIMIT", "Rendered PDF page exceeds the pixel cap", 4)
            prefix = stage / f"page-{number}"
            run(
                [
                    executable("pdftoppm"),
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    "-r",
                    str(dpi),
                    "-singlefile",
                    "-png",
                    str(path),
                    str(prefix),
                ],
                request.deadline,
                file_cap=remaining,
                output_files=(Path(str(prefix) + ".png"),),
            )
            image = Path(str(prefix) + ".png")
            content = bounded_read(image, remaining)
            remaining -= len(content)
            current, dimensions = _image(image, spec, request.deadline, number)
            segments.extend(current)
            children.append(
                {
                    "raw": content,
                    "media_type": "image/png",
                    "mapping": {"physical_page": number, **dimensions, "dpi": dpi},
                }
            )
            pages.append(number)
        coverage = {
            "physical_pages": len(reader.pages),
            "processed_pages": pages,
            "unprocessed_pages": [n for n in range(1, len(reader.pages) + 1) if n not in pages],
            "ocr_used": True,
            "text_layer_used": False,
        }
    if not segments:
        raise CoreError("OCR_EMPTY", "OCR produced no usable text; no invented fallback", 3)
    return {
        "status": "partial" if any(s["uncertain"] for s in segments) else "ok",
        "engine": profile("tesseract"),
        "segments": segments,
        "coverage": coverage,
        "children": children,
        "limitations": [
            "OCR is not proof of critical numbers/negations; flagged spans require separate sample verification",
            "Physical-page/pixel locators; no table/UX behavior inference",
        ],
    }
