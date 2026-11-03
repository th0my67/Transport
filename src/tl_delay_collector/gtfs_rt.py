from datetime import datetime, timezone

from .config import GTFS_RT_URL
from .utils import jget, local_service_date, norm_rel, to_int


def poll_gtfs_rt(http, api_key):
    r = http.get(GTFS_RT_URL, params={"format": "JSON"},
                 headers={"Authorization": f"Bearer {api_key}"},
                 timeout=120)
    r.raise_for_status()
    return r.json()


def feed_timestamp(feed):
    header = jget(feed, "header", "Header") or {}
    raw = jget(header, "timestamp", "Timestamp")
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).isoformat(
            timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def parse_tl_entities(feed, now_iso, tl_route_ids, tl_trip_routes):
    """Filtre le flux et retourne (trip_rows, stop_rows) à insérer."""
    entities = feed if isinstance(feed, list) else jget(feed, "entity", "Entity",
                                                        default=[])
    if not isinstance(entities, list):
        entities = []
    trip_rows, stop_rows = [], []
    for entity in entities:
        tu = jget(entity, "tripUpdate", "TripUpdate", "trip_update")
        if not isinstance(tu, dict):
            continue
        trip = jget(tu, "trip", "Trip") or {}
        trip_id = jget(trip, "tripId", "TripId")
        route_id = jget(trip, "routeId", "RouteId")
        if route_id is None and trip_id in tl_trip_routes:
            route_id = tl_trip_routes[trip_id]
        if trip_id is None and route_id is None:
            continue
        if route_id not in tl_route_ids and trip_id not in tl_trip_routes:
            continue
        start_date = str(jget(trip, "startDate", "StartDate")
                         or local_service_date())
        rel = norm_rel(jget(trip, "scheduleRelationship", "ScheduleRelationship"))
        trip_rows.append({
            "start_date": start_date, "trip_id": trip_id, "route_id": route_id,
            "vehicle_id": jget(jget(tu, "vehicle", "Vehicle") or {},
                               "id", "Id"),
            "schedule_relationship": rel,
            "ever_canceled": 1 if "CANCELED" in rel else 0,
            "first_seen": now_iso, "last_seen": now_iso,
        })
        for stu in (jget(tu, "stopTimeUpdate", "StopTimeUpdate",
                         "stop_time_update") or []):
            seq = to_int(jget(stu, "stopSequence", "StopSequence"))
            if seq is None:
                continue
            arrival = jget(stu, "arrival", "Arrival") or {}
            departure = jget(stu, "departure", "Departure") or {}
            arr_delay = to_int(jget(arrival, "delay", "Delay")
                               if isinstance(arrival, dict)
                               else jget(stu, "arrivalDelay", "ArrivalDelay"))
            dep_delay = to_int(jget(departure, "delay", "Delay")
                               if isinstance(departure, dict)
                               else jget(stu, "departureDelay", "DepartureDelay"))
            stop_rows.append({
                "start_date": start_date, "trip_id": trip_id,
                "stop_sequence": seq, "route_id": route_id,
                "stop_id": jget(stu, "stopId", "StopId"),
                "stop_rel": norm_rel(jget(stu, "scheduleRelationship",
                                          "ScheduleRelationship")),
                "first_seen": now_iso, "last_seen": now_iso,
                "first_arr_delay": arr_delay, "last_arr_delay": arr_delay,
                "first_dep_delay": dep_delay, "last_dep_delay": dep_delay,
            })
    return trip_rows, stop_rows
