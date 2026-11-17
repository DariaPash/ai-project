"""Exact arithmetic for explicitly supplied option judgments, not market evidence."""

from decimal import Decimal


def weighted_score(scores, weights):
    if not weights or set(weights) - set(scores):
        raise ValueError("Every weighted criterion needs a score")
    values = [Decimal(str(value)) for value in weights.values()]
    if any(not v.is_finite() or v < 0 for v in values) or sum(values) != Decimal(1):
        raise ValueError("Weights must be finite, nonnegative and sum to one")
    ratings = [Decimal(str(scores[name])) for name in weights]
    if any(not v.is_finite() for v in ratings):
        raise ValueError("Scores must be finite")
    return sum((weight * rating for weight, rating in zip(values, ratings)), Decimal(0))


def scenario(options, weights):
    totals = {option["id"]: weighted_score(option["payload"]["scores"], weights) for option in options}
    best = max(totals.values())
    return totals, [identity for identity, value in totals.items() if value == best]
