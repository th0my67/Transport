from tl_delay_collector.gtfs_rt import feed_timestamp, parse_tl_entities

TL_ROUTES = {"91:1"}
TL_TRIPS = {"trip-1": "91:1"}


def _feed_camel(entity):
    return {"header": {"timestamp": 1_700_000_000},
            "entity": [{"id": "e1", "tripUpdate": entity}]}


def test_parse_filters_non_tl_and_extracts_delays():
    feed = _feed_camel({
        "trip": {"tripId": "trip-1", "routeId": "91:1", "startDate": "20260101"},
        "vehicle": {"id": "veh-9"},
        "stopTimeUpdate": [
            {"stopSequence": 3, "stopId": "s3",
             "arrival": {"delay": 120}, "departure": {"delay": 130}},
        ],
    })
    feed["entity"].append({"id": "e2", "tripUpdate": {
        "trip": {"tripId": "autre", "routeId": "11:1"}}})
    trip_rows, stop_rows = parse_tl_entities(feed, "2026-01-01T00:00:00+00:00",
                                             TL_ROUTES, TL_TRIPS)
    assert len(trip_rows) == 1
    assert trip_rows[0]["trip_id"] == "trip-1"
    assert trip_rows[0]["vehicle_id"] == "veh-9"
    assert trip_rows[0]["ever_canceled"] == 0
    assert len(stop_rows) == 1
    assert stop_rows[0]["stop_sequence"] == 3
    assert stop_rows[0]["first_arr_delay"] == 120
    assert stop_rows[0]["last_dep_delay"] == 130


def test_parse_pascal_case_and_canceled():
    feed = {"Header": {"Timestamp": 1_700_000_000},
            "Entity": [{"Id": "e1", "TripUpdate": {
                "Trip": {"TripId": "trip-1", "RouteId": "91:1",
                         "StartDate": "20260101",
                         "ScheduleRelationship": 4},
                "StopTimeUpdate": [{"StopSequence": "1",
                                    "StopId": "s1",
                                    "Arrival": {"Delay": "45"}}],
            }}]}
    trip_rows, stop_rows = parse_tl_entities(feed, "now", TL_ROUTES, TL_TRIPS)
    assert trip_rows[0]["schedule_relationship"] == "CANCELED"
    assert trip_rows[0]["ever_canceled"] == 1
    assert stop_rows[0]["first_arr_delay"] == 45
    assert stop_rows[0]["last_arr_delay"] == 45


def test_parse_resolves_route_from_trip_map():
    feed = _feed_camel({"trip": {"tripId": "trip-1", "startDate": "20260101"},
                        "stopTimeUpdate": []})
    trip_rows, _ = parse_tl_entities(feed, "now", TL_ROUTES, TL_TRIPS)
    assert trip_rows[0]["route_id"] == "91:1"


def test_feed_timestamp():
    feed = {"header": {"timestamp": 1_700_000_000}}
    assert feed_timestamp(feed) == "2023-11-14T22:13:20+00:00"
    assert feed_timestamp({}) is None
    assert feed_timestamp({"header": {"timestamp": "abc"}}) is None
