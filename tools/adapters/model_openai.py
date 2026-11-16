"""Explicit unavailable boundary; no undocumented or unapproved provider call."""

from ..errors import CoreError


def execute(request):
    raise CoreError(
        "MODEL_API_BLOCKED",
        "No approved endpoint/model/budget/data-transfer scope and no installed httpx. No API request was made.",
        3,
    )
