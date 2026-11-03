import logging
import os
from datetime import datetime, timezone

from .config import ZURICH

log = logging.getLogger("tl-collector")


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_service_date():
    """Date de service (jour calendrier à Zurich) si le flux l'omet."""
    return datetime.now(ZURICH).strftime("%Y%m%d")


def to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def jget(d, *names, default=None):
    """Cherche une clé dans un dictionnaire en essayant plusieurs graphies
    (la variante JSON du flux est non standardisée : tripUpdate / TripUpdate...)."""
    if not isinstance(d, dict):
        return default
    for name in names:
        if name in d:
            return d[name]
    return default


REL_CODES = {1: "SCHEDULED", 2: "SKIPPED", 3: "NO_DATA", 4: "CANCELED"}


def norm_rel(value):
    if value is None:
        return "SCHEDULED"
    if isinstance(value, int):
        return REL_CODES.get(value, str(value))
    return str(value).upper().replace("CANCELLED", "CANCELED")


def db_size_mb(db_spec):
    if "://" in db_spec:
        return 0.0
    try:
        return os.path.getsize(db_spec) / 1e6
    except OSError:
        return 0.0
