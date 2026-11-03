from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import UPSERT_CHUNK
from .gtfs_rt import parse_tl_entities
from .models import MetaKV, PollLog, StopDelay, StopTime, TlRoute, TripStatus
from .utils import jget, log, utcnow_iso


def get_meta(Session_factory, key):
    with Session_factory() as session:
        row = session.get(MetaKV, key)
        return row.value if row else None


def set_meta(Session_factory, key, value):
    with Session_factory.begin() as session:
        session.merge(MetaKV(key=key, value=str(value)))


def load_tl_maps(Session_factory):
    """Charge les filtres TL depuis la base : route_ids et trip_id -> route_id."""
    with Session_factory() as session:
        route_ids = set(session.scalars(select(TlRoute.route_id)))
        if not route_ids:
            raise RuntimeError("Base sans GTFS statique : lancez d'abord "
                               "--import-only.")
        trip_routes = dict(
            session.execute(
                select(StopTime.trip_id, StopTime.route_id).distinct()
            ).all())
    log.info("Filtres TL chargés : %d lignes, %d courses.",
             len(route_ids), len(trip_routes))
    return route_ids, trip_routes


def record_feed(Session_factory, feed, now_iso, tl_route_ids, tl_trip_routes):
    """Filtre les trip updates TL, les upserte en base et journalise le poll.
    Retourne (nb entités totales, nb courses TL, nb mises à jour d'arrêts)."""
    trip_rows, stop_rows = parse_tl_entities(feed, now_iso,
                                             tl_route_ids, tl_trip_routes)
    with Session_factory.begin() as session:
        for start in range(0, len(trip_rows), UPSERT_CHUNK):
            chunk = trip_rows[start:start + UPSERT_CHUNK]
            stmt = sqlite_insert(TripStatus).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["start_date", "trip_id"],
                set_={
                    "route_id": func.coalesce(stmt.excluded.route_id,
                                              TripStatus.route_id),
                    "vehicle_id": func.coalesce(stmt.excluded.vehicle_id,
                                                TripStatus.vehicle_id),
                    "schedule_relationship": stmt.excluded.schedule_relationship,
                    "ever_canceled": func.max(TripStatus.ever_canceled,
                                              stmt.excluded.ever_canceled),
                    "last_seen": stmt.excluded.last_seen,
                    "n_updates": TripStatus.n_updates + 1,
                },
            )
            session.execute(stmt)
        for start in range(0, len(stop_rows), UPSERT_CHUNK):
            chunk = stop_rows[start:start + UPSERT_CHUNK]
            stmt = sqlite_insert(StopDelay).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["start_date", "trip_id", "stop_sequence"],
                set_={
                    "route_id": func.coalesce(stmt.excluded.route_id,
                                              StopDelay.route_id),
                    "stop_id": func.coalesce(stmt.excluded.stop_id,
                                             StopDelay.stop_id),
                    "stop_rel": stmt.excluded.stop_rel,
                    "last_seen": stmt.excluded.last_seen,
                    "last_arr_delay": func.coalesce(
                        stmt.excluded.last_arr_delay, StopDelay.last_arr_delay),
                    "last_dep_delay": func.coalesce(
                        stmt.excluded.last_dep_delay, StopDelay.last_dep_delay),
                    "n_updates": StopDelay.n_updates + 1,
                },
            )
            session.execute(stmt)
    n_entities = len(feed) if isinstance(feed, list) else len(
        jget(feed, "entity", "Entity", default=[]) or [])
    return n_entities, len(trip_rows), len(stop_rows)


def log_poll(Session_factory, ok, http_status=None, n_entities=0, n_tl=0,
             n_rows=0, duration_ms=0, error=None, feed_ts=None):
    with Session_factory.begin() as session:
        session.add(PollLog(
            ts=utcnow_iso(), feed_ts=feed_ts, ok=int(ok),
            http_status=http_status, n_entities=n_entities,
            n_tl=n_tl, n_stop_updates=n_rows,
            duration_ms=int(duration_ms), error=error))
