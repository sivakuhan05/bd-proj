from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def score_to_three_class_label(score: float) -> str:
    if score <= -0.2:
        return "Left"
    if score >= 0.2:
        return "Right"
    return "Center"
