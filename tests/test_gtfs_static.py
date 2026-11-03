import io
import zipfile

import pytest
from sqlalchemy import func, select

from tl_delay_collector.gtfs_static import import_static_zip, is_tl_agency
from tl_delay_collector.models import MetaKV, Stop, StopTime, TlRoute
from tl_delay_collector.repository import get_meta, load_tl_maps

GTFS_FILES = {
    "feed_info.txt": "feed_publisher_name,feed_version\ntest,2026.01\n",
    "agency.txt": ("agency_id,agency_name\n"
                   "TL,Transports publics lausannois\n"
                   "SBB,CFF\n"),
    "routes.txt": ("route_id,agency_id,route_short_name,route_long_name,route_type\n"
                   "91:1,TL,1,Prilly - Lausanne,3\n"
                   "11:1,SBB,IR90,Genève - Brig,1\n"),
    "trips.txt": ("route_id,trip_id\n"
                  "91:1,trip-1\n"
                  "11:1,trip-sbb\n"),
    "stop_times.txt": ("trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                       "trip-1,08:00:00,08:00:00,s1,1\n"
                       "trip-1,08:10:00,08:10:00,s2,2\n"
                       "trip-sbb,09:00:00,09:00:00,s1,1\n"),
    "stops.txt": ("stop_id,stop_name,stop_lat,stop_lon\n"
                  "s1,Arrêt Un,46.52,6.63\n"
                  "s2,Arrêt Deux,46.53,6.64\n"
                  "s3,Arrêt SBB,46.0,7.0\n"),
}


def _make_gtfs_zip(path, version="2026.01"):
    files = dict(GTFS_FILES)
    files["feed_info.txt"] = f"feed_publisher_name,feed_version\ntest,{version}\n"
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return path


def test_is_tl_agency():
    assert is_tl_agency("Transports publics lausannois")
    assert is_tl_agency("TL")
    assert not is_tl_agency("CFF")
    assert not is_tl_agency("")


def test_import_static_zip(session_factory, tmp_path):
    zip_path = _make_gtfs_zip(tmp_path / "gtfs.zip")
    assert import_static_zip(session_factory, str(zip_path)) is True

    with session_factory() as session:
        routes = session.scalars(select(TlRoute.route_id)).all()
        assert routes == ["91:1"]
        n_stop_times = session.scalar(
            select(func.count()).select_from(StopTime))
        assert n_stop_times == 2
        stops = session.scalars(select(Stop.stop_id)).all()
        assert sorted(stops) == ["s1", "s2"]
    assert get_meta(session_factory, "static_feed_version") == "2026.01"

    route_ids, trip_routes = load_tl_maps(session_factory)
    assert route_ids == {"91:1"}
    assert trip_routes == {"trip-1": "91:1"}


def test_import_static_zip_skips_same_version(session_factory, tmp_path):
    zip_path = _make_gtfs_zip(tmp_path / "gtfs.zip", version="2026.01")
    assert import_static_zip(session_factory, str(zip_path)) is True
    assert import_static_zip(session_factory, str(zip_path)) is False


def test_import_static_zip_reimports_new_version(session_factory, tmp_path):
    zip_path = _make_gtfs_zip(tmp_path / "gtfs.zip", version="2026.01")
    assert import_static_zip(session_factory, str(zip_path)) is True
    zip_path2 = _make_gtfs_zip(tmp_path / "gtfs2.zip", version="2026.02")
    assert import_static_zip(session_factory, str(zip_path2)) is True
    assert get_meta(session_factory, "static_feed_version") == "2026.02"


def test_import_without_tl_routes_raises(session_factory, tmp_path):
    files = dict(GTFS_FILES)
    files["agency.txt"] = "agency_id,agency_name\nSBB,CFF\n"
    files["routes.txt"] = ("route_id,agency_id,route_short_name,route_type\n"
                           "11:1,SBB,IR90,1\n")
    zip_path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    with pytest.raises(RuntimeError, match="Aucune ligne TL"):
        import_static_zip(session_factory, str(zip_path))
