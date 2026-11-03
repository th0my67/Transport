import pytest

from tl_delay_collector.gtfs_static import find_gtfs_static_url


class FakeResp:
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, search=None, search_ok=True, shows=None):
        self.search = search
        self.search_ok = search_ok
        self.shows = shows or {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if "package_search" in url:
            return FakeResp(self.search, ok=self.search_ok,
                            status=200 if self.search_ok else 500)
        if "package_show" in url:
            payload = self.shows.get(params["id"])
            if payload is None:
                return FakeResp({}, ok=False, status=404)
            return FakeResp(payload)
        raise AssertionError(f"appel inattendu : {url}")


def _dataset(name, zips, modified="2026-11-01T00:00:00"):
    return {"name": name, "metadata_modified": modified,
            "resources": [{"url": u, "last_modified": modified} for u in zips]}


def test_search_picks_gtfs_dataset_with_zip():
    http = FakeHttp(search={"success": True, "result": {"results": [
        _dataset("horaires-hiver-hrdf", []),
        _dataset("timetable-2026-gtfs2020",
                 ["https://x/gtfs_fp2026_20261101.zip"]),
    ]}})
    name, url = find_gtfs_static_url(http)
    assert name == "timetable-2026-gtfs2020"
    assert url.endswith("gtfs_fp2026_20261101.zip")


def test_search_picks_most_recent_zip_resource():
    http = FakeHttp(search={"success": True, "result": {"results": [
        {"name": "timetable-2026-gtfs2020", "resources": [
            {"url": "https://x/gtfs_old.zip", "last_modified": "2026-01-01"},
            {"url": "https://x/gtfs_new.zip", "last_modified": "2026-10-01"},
        ]},
    ]}})
    _, url = find_gtfs_static_url(http)
    assert url.endswith("gtfs_new.zip")


def test_zip_detected_by_format_when_url_has_no_extension():
    http = FakeHttp(search={"success": True, "result": {"results": [
        {"name": "timetable-2026-gtfs2020", "resources": [
            {"url": "https://x/download/abc123", "format": "ZIP"},
        ]},
    ]}})
    _, url = find_gtfs_static_url(http)
    assert url == "https://x/download/abc123"


def test_falls_back_to_candidates_when_search_fails():
    http = FakeHttp(search_ok=False, shows={
        "timetable-2027-gtfs2020": {"success": True, "result": {"resources": []}},
        "timetable-2026-gtfs2020": {"success": True, "result": {"resources": [
            {"url": "https://x/gtfs2026.zip"}]}},
    })
    name, url = find_gtfs_static_url(http)
    assert (name, url) == ("timetable-2026-gtfs2020", "https://x/gtfs2026.zip")


def test_raises_when_nothing_found():
    http = FakeHttp(search={"success": True, "result": {"results": []}},
                    shows={})
    with pytest.raises(RuntimeError, match="GTFS statique"):
        find_gtfs_static_url(http)
