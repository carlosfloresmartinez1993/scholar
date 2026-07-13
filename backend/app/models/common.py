from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC — all timestamp columns are TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
