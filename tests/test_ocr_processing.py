import json
import shutil
import pytest
from tools.contracts import key
from tools.errors import CoreError
from tools.sources import ingest
from tools.store import Store
from .helpers import PROJECT, init
from .step03_helpers import Fixture
from .step04_helpers import prepare_media, import_media


@pytest.mark.parametrize("format_name", ["image", "scan_pdf"])
def test_real_local_ocr_with_uncertainty_and_locations(project, format_name):
    if not shutil.which("tesseract") or (format_name == "scan_pdf" and not shutil.which("pdftoppm")):
        pytest.skip("Local Tesseract/Poppler missing: live OCR not passed")
    prepare_media(project)
    init(project)
    saved, extraction = import_media(project, format_name)
    media = extraction["payload"]["coverage"]["media"]
    assert media["engine"]["engine"] == "tesseract" and media["segments"]
    assert any(s["uncertain"] for s in media["segments"])
    assert extraction["lineage_roots"] == ["synthetic_fixture"]
    for segment in media["segments"]:
        assert segment["kind"] == "image" and segment["coordinates"]["width"] > 0
        if format_name == "scan_pdf":
            assert segment["coordinates"]["physical_page"] == 1
    # A high engine confidence is not a permission to promote a critical token.
    segment = next(s for s in media["segments"] if s["uncertain"])
    locator = {
        "source_revision": saved["data"]["source_ref"]["revision"],
        "source_hash": saved["data"]["source_sha256"],
        "extraction_id": saved["data"]["extraction_ref"]["entity_id"],
        "kind": segment["kind"],
        "coordinates": segment["coordinates"],
        "exact_quote": segment["text"],
    }
    f = Fixture(project)
    with pytest.raises(CoreError) as error:
        f.record(
            "claim",
            {
                "text": "A critical media token is certainly correct",
                "type": "fact",
                "status": "supported",
                "support_scope": "technical_fixture",
                "support_review": "Unverified confidence is not enough",
                "origin": "synthetic_fixture",
                "evidence": [{"ref": saved["data"]["source_ref"], "locator": locator}],
                "counterevidence": [],
                "basis_refs": [],
                "limitations": [],
            },
        )
    assert error.value.code == "UNCERTAIN_MEDIA"
    with Store(project, "test-core") as store:
        assert store.validate()["warnings"] == []
