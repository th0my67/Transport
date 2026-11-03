from tl_delay_collector.utils import jget, norm_rel, to_int


def test_to_int_rounds_and_handles_bad_values():
    assert to_int(None) is None
    assert to_int("12.4") == 12
    assert to_int(7.6) == 8
    assert to_int("pas un nombre") is None


def test_jget_tries_multiple_keys():
    assert jget({"tripId": "t1"}, "tripId", "TripId") == "t1"
    assert jget({"TripId": "t2"}, "tripId", "TripId") == "t2"
    assert jget({"autre": 1}, "tripId", default="d") == "d"
    assert jget(None, "tripId", default="d") == "d"


def test_norm_rel():
    assert norm_rel(None) == "SCHEDULED"
    assert norm_rel(4) == "CANCELED"
    assert norm_rel(1) == "SCHEDULED"
    assert norm_rel("CANCELLED") == "CANCELED"
    assert norm_rel("skipped") == "SKIPPED"
