from sqlalchemy import select

from tl_delay_collector.models import PollLog, StopDelay, TripStatus
from tl_delay_collector.repository import log_poll, record_feed

TL_ROUTES = {"91:1"}
TL_TRIPS = {"trip-1": "91:1"}


def _feed(delay):
    return {"header": {"timestamp": 1_700_000_000},
            "entity": [{"id": "e1", "tripUpdate": {
                "trip": {"tripId": "trip-1", "routeId": "91:1",
                         "startDate": "20260101"},
                "stopTimeUpdate": [
                    {"stopSequence": 1, "stopId": "s1",
                     "arrival": {"delay": delay}, "departure": {"delay": delay}},
                ],
            }}]}


def test_record_feed_upserts_and_preserves_first_observation(session_factory):
    n_entities, n_tl, n_rows = record_feed(session_factory, _feed(60), "t1",
                                           TL_ROUTES, TL_TRIPS)
    assert (n_entities, n_tl, n_rows) == (1, 1, 1)
    record_feed(session_factory, _feed(180), "t2", TL_ROUTES, TL_TRIPS)
    record_feed(session_factory, _feed(None), "t3", TL_ROUTES, TL_TRIPS)

    with session_factory() as session:
        trip = session.get(TripStatus, ("20260101", "trip-1"))
        assert trip.n_updates == 3
        assert trip.last_seen == "t3"
        delay = session.get(StopDelay, ("20260101", "trip-1", 1))
        assert delay.n_updates == 3
        assert delay.first_arr_delay == 60
        assert delay.first_dep_delay == 60
        assert delay.last_arr_delay == 180
        assert delay.last_dep_delay == 180


def test_record_feed_ignores_non_tl(session_factory):
    feed = {"entity": [{"id": "e1", "tripUpdate": {
        "trip": {"tripId": "x", "routeId": "11:1"}}}]}
    n_entities, n_tl, n_rows = record_feed(session_factory, feed, "t1",
                                           TL_ROUTES, TL_TRIPS)
    assert (n_entities, n_tl, n_rows) == (1, 0, 0)
    with session_factory() as session:
        assert session.scalars(select(TripStatus)).all() == []


def test_log_poll(session_factory):
    log_poll(session_factory, ok=1, http_status=200, n_entities=10, n_tl=3,
             n_rows=25, duration_ms=120, feed_ts="2023-11-14T22:13:20+00:00")
    with session_factory() as session:
        row = session.scalars(select(PollLog)).one()
        assert row.ok == 1
        assert row.http_status == 200
        assert row.n_entities == 10
        assert row.n_tl == 3
        assert row.n_stop_updates == 25
        assert row.duration_ms == 120
