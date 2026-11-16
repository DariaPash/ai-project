"""Write explicit synthetic inputs, never calculate their expected answers.

Once manifests exist, verify their hashes instead of regenerating fixtures.
"""

import csv
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import zipfile

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from tools.contracts import sha
from tools.development import ROOT, now, write_json

Q = ROOT / "tests/fixtures/quantitative"
S = ROOT / "tests/fixtures/sources"


def csv_bytes(header, rows):
    import io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode()


def pdf_bytes(texts=None):
    writer = PdfWriter()
    if texts is None:
        page = writer.add_blank_page(width=200, height=200)
        image = DecodedStreamObject()
        image.set_data(b"\x80" * 100)
        image.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(10),
                NameObject("/Height"): NumberObject(10),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)})}
        )
        content = DecodedStreamObject()
        content.set_data(b"q 100 0 0 100 0 0 cm /Im1 Do Q")
        page[NameObject("/Contents")] = writer._add_object(content)
    else:
        for text in texts:
            page = writer.add_blank_page(width=400, height=300)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
            )
            content = DecodedStreamObject()
            content.set_data(("BT /F1 12 Tf 20 250 Td (" + text + ") Tj ET").encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    assert Path(progress["active_run"]).parts[2] == "02"
    if (Q / "manifest.json").exists():
        for folder in (Q, S):
            manifest = json.loads((folder / "manifest.json").read_text())
            for name, expected in manifest["files"].items():
                assert sha((folder / name).read_bytes()) == expected, "Existing frozen fixture differs"
        print("Existing step02 fixture hashes verified; no regeneration")
        return
    registrations = [
        [
            f"U{i:02}",
            "2026-10-20" if i <= 10 else "2026-10-28" if i <= 15 else "2026-11-05",
            "small" if i <= 10 or i > 15 else "agency",
        ]
        for i in range(1, 20)
    ]
    registrations.append(registrations[0].copy())
    d7 = [[f"U{i:02}", "2026-10-27" if i <= 10 else "2026-11-04"] for i in [1, 2, 3, 4, 11, 12, 13]]
    d7 += [d7[0].copy(), ["", "2026-10-27"]]
    activations = [[f"U{i:02}", "2026-10-21" if i <= 10 else "2026-10-29"] for i in [1, 2, 3, 4, 5, 6, 11, 12, 13, 14]]
    economy = [
        ["payers", "100", "RUB", "month"],
        ["price", "1000", "RUB", "month"],
        ["variable_cost", "200", "RUB", "month"],
        ["fixed_cost", "50000", "RUB", "month"],
        ["investment", "60000", "RUB", "one_time"],
        ["incremental_net", "10000", "RUB", "month"],
    ]
    tables = {
        "registrations": (["user_id", "signup_at", "segment"], registrations),
        "d7": (["user_id", "event_at"], d7),
        "activations": (["user_id", "event_at"], activations),
        "economics": (["name", "value", "currency", "period"], economy),
    }
    outputs = {Q / (name + ".csv"): csv_bytes(*data) for name, data in tables.items()}
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = workbook.properties.modified = datetime(2026, 11, 8)
    for name, (header, rows) in tables.items():
        sheet = workbook.create_sheet(name)
        sheet.append(header)
        for row in rows:
            sheet.append(row)
    sheet = workbook.create_sheet("formula")
    sheet.append(["name", "value"])
    sheet.append(["computed", "=1+1"])
    out = BytesIO()
    workbook.save(out)
    deterministic = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(out.getvalue())) as original,
        zipfile.ZipFile(deterministic, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for name in original.namelist():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, original.read(name))
    outputs[S / "tables.xlsx"] = deterministic.getvalue()
    outputs[S / "document.pdf"] = pdf_bytes(
        ["Technical fixture page one.", "Known number: 15. This is not market evidence."]
    )
    outputs[S / "image-only.pdf"] = pdf_bytes()
    outputs[S / "corrupt.pdf"] = b"%PDF-1.7\nnot a valid document"
    outputs[S / "corrupt.xlsx"] = b"not a zip workbook"
    outputs[S / "multiline.csv"] = csv_bytes(
        ["id", "note"], [["A", "First line\nSecond line"], ["B", '=HYPERLINK("https://example.invalid")']]
    )
    for path, raw in outputs.items():
        assert not path.exists(), "Never overwrite an existing fixture"
        path.write_bytes(raw)
    for folder in (Q, S):
        files = {path.name: sha(path.read_bytes()) for path in sorted(folder.iterdir()) if path.is_file()}
        write_json(
            folder / "manifest.json",
            {
                "schema_version": 1,
                "origin": "synthetic_fixture",
                "as_of": "2026-11-08T00:00:00Z",
                "generator": "tests/build_step02_fixtures.py",
                "generator_sha256": sha(Path(__file__).read_bytes()),
                "rights": {"processing": True, "external_transfer": False, "publication": False},
                "files": files,
                "oracle": "oracle.json",
                "limitations": "Artificial technical corpus; no market claims or measured business baseline",
            },
        )
    freeze = {
        "frozen_at": now(),
        "origin": "synthetic_fixture",
        "files": {
            str(path.relative_to(ROOT)): sha(path.read_bytes())
            for folder in (Q, S)
            for path in sorted(folder.iterdir())
            if path.is_file()
        },
    }
    write_json(ROOT / progress["active_run"] / "fixture-freeze.json", freeze)
    print(
        json.dumps(
            {
                "frozen_inputs": len(freeze["files"]),
                "frozen_at": freeze["frozen_at"],
                "expected_results": "hand-authored oracle; no production calculation was called",
            }
        )
    )


if __name__ == "__main__":
    main()
