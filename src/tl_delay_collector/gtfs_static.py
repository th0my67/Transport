import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

import requests

from .config import (AGENCY_NAME_HINTS, CKAN_API_BASE, GTFS_DATASET_CANDIDATES,
                     GTFS_SEARCH_QUERY, ROUTE_ID_PREFIXES)
from .models import MetaKV, Stop, StopTime, TlRoute
from .repository import get_meta, load_tl_maps
from .utils import log, to_int, utcnow_iso


def is_tl_agency(agency_name):
    name = (agency_name or "").strip().lower()
    if not name:
        return False
    if name == "tl":
        return True
    return any(hint in name for hint in AGENCY_NAME_HINTS)


def _zip_resources(resources):
    """Extrait les ressources ZIP d'un dataset CKAN, de la plus récente à la
    plus ancienne (accepte une URL en .zip ou un format/name « ZIP »)."""
    zips = []
    for res in resources:
        url = str(res.get("url", ""))
        fmt = str(res.get("format", "")).upper()
        name = str(res.get("name", ""))
        if url.endswith(".zip") or "ZIP" in fmt or name.lower().endswith(".zip"):
            stamp = str(res.get("last_modified") or res.get("created") or "")
            zips.append((stamp, url))
    return sorted(zips, reverse=True)


def _auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _find_via_search(http, api_key):
    """Recherche CKAN dynamique : dataset « timetable … gtfs » le plus récent."""
    r = http.get(f"{CKAN_API_BASE}/package_search",
                 params={"q": GTFS_SEARCH_QUERY, "rows": 25,
                         "sort": "metadata_modified desc"},
                 headers=_auth_headers(api_key), timeout=60)
    if not r.ok:
        log.warning("CKAN package_search : HTTP %s", r.status_code)
        return None
    payload = r.json()
    if not payload.get("success"):
        return None
    for dataset in payload.get("result", {}).get("results", []):
        name = str(dataset.get("name", ""))
        if "gtfs" not in name.lower():
            continue
        zips = _zip_resources(dataset.get("resources", []))
        if zips:
            log.info("GTFS statique trouvé par recherche CKAN : dataset %s",
                     name)
            return name, zips[0][1]
    return None


def _find_via_candidates(http, api_key):
    """Repli : interroge les datasets connus un par un (package_show)."""
    for dataset in GTFS_DATASET_CANDIDATES:
        try:
            r = http.get(f"{CKAN_API_BASE}/package_show",
                         params={"id": dataset},
                         headers=_auth_headers(api_key), timeout=60)
            if not r.ok:
                log.warning("CKAN package_show %s : HTTP %s", dataset,
                            r.status_code)
                continue
            payload = r.json()
            if not payload.get("success"):
                continue
            zips = _zip_resources(payload.get("result", {}).get("resources", []))
            if zips:
                return dataset, zips[0][1]
        except requests.RequestException as exc:
            log.warning("CKAN %s indisponible : %s", dataset, exc)
    return None


def find_gtfs_static_url(http, api_key=None):
    """Trouve l'URL du dernier ZIP GTFS statique via l'API CKAN (recherche
    dynamique d'abord, datasets connus en repli)."""
    try:
        found = _find_via_search(http, api_key)
    except requests.RequestException as exc:
        log.warning("CKAN package_search indisponible : %s", exc)
        found = None
    if found is None:
        found = _find_via_candidates(http, api_key)
    if found is None:
        raise RuntimeError(
            "Impossible de trouver le GTFS statique automatiquement (l'API "
            "CKAN api.opentransportdata.swiss/ckan-api exige une clé : passez "
            "--api-key / OTD_API_KEY). Sinon, téléchargez le ZIP sur "
            "https://opendata.swiss (recherche : « horaire GTFS2020 »), puis "
            "relancez avec --gtfs-url /chemin/vers/GTFS.zip"
        )
    return found


def download_file(http, url, dest):
    log.info("Téléchargement de %s", url)
    with http.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    log.info("Téléchargé : %.1f Mo", os.path.getsize(dest) / 1e6)


def import_static_zip(Session_factory, zip_path):
    """Importe l'horaire théorique TL depuis un ZIP GTFS. Retourne False si la
    version du feed est identique à celle déjà en base (rien à faire)."""
    with zipfile.ZipFile(zip_path) as z:
        members = {Path(n).name: n for n in z.namelist() if n.endswith(".txt")}

        def reader(name):
            return io.TextIOWrapper(z.open(members[name]),
                                    encoding="utf-8-sig", newline="")

        # Version du feed (les IDs de courses changent à chaque version)
        feed_version = None
        if "feed_info.txt" in members:
            for row in csv.DictReader(reader("feed_info.txt")):
                feed_version = row.get("feed_version")
                break
        if feed_version and feed_version == get_meta(Session_factory,
                                                    "static_feed_version"):
            log.info("GTFS statique déjà en base (version %s), rien à "
                     "importer.", feed_version)
            return False
        log.info("Nouveau GTFS statique : version %s", feed_version or "?")

        # Entreprises -> TL
        agencies = [(row.get("agency_id"), row.get("agency_name"))
                    for row in csv.DictReader(reader("agency.txt"))]
        log.info("Entreprises dans agency.txt : %s",
                 ", ".join(f"{aid}={name}" for aid, name in agencies[:25]))
        tl_agency_ids = {aid for aid, name in agencies
                         if is_tl_agency(name)
                         or (aid or "").strip().upper() == "TL"}
        if not tl_agency_ids:
            log.warning("Aucune entreprise TL détectée via agency.txt ! "
                        "Vérifiez la liste ci-dessus et ajustez "
                        "AGENCY_NAME_HINTS.")
        else:
            log.info("TL détecté : %s",
                     [name for aid, name in agencies if aid in tl_agency_ids])

        # Lignes TL
        tl_route_ids, tl_route_rows = set(), []
        for row in csv.DictReader(reader("routes.txt")):
            route_id = row.get("route_id")
            if not route_id:
                continue
            if (row.get("agency_id") in tl_agency_ids
                    or any(route_id.startswith(p) for p in ROUTE_ID_PREFIXES)):
                tl_route_ids.add(route_id)
                tl_route_rows.append({
                    "route_id": route_id,
                    "agency_id": row.get("agency_id"),
                    "route_short_name": row.get("route_short_name"),
                    "route_long_name": row.get("route_long_name"),
                    "route_type": to_int(row.get("route_type")),
                })
        if not tl_route_ids:
            raise RuntimeError(
                "Aucune ligne TL détectée dans routes.txt. Lancez avec "
                "--import-only et vérifiez la liste des entreprises ci-dessus, "
                "puis corrigez AGENCY_NAME_HINTS ou ROUTE_ID_PREFIXES."
            )
        tl_numbers = sorted({r["route_short_name"] or r["route_id"]
                            for r in tl_route_rows})
        log.info("Lignes TL détectées : %d (%s...)", len(tl_route_ids),
                 ", ".join(tl_numbers[:15]))

        # Courses TL (trip_id -> route_id)
        tl_trip_routes = {}
        for row in csv.DictReader(reader("trips.txt")):
            trip_id, route_id = row.get("trip_id"), row.get("route_id")
            if trip_id and route_id in tl_route_ids:
                tl_trip_routes[trip_id] = route_id
        log.info("Courses TL dans l'horaire : %d", len(tl_trip_routes))

        # stop_times : uniquement les courses TL (insertion par lots)
        used_stops, batch, total = set(), [], 0
        with Session_factory.begin() as session:
            stop_stmt = StopTime.__table__.insert().prefix_with("OR REPLACE")
            for row in csv.DictReader(reader("stop_times.txt")):
                trip_id = row.get("trip_id")
                if trip_id not in tl_trip_routes:
                    continue
                batch.append({
                    "trip_id": trip_id,
                    "stop_sequence": to_int(row.get("stop_sequence")) or 0,
                    "stop_id": row.get("stop_id"),
                    "arrival_time": row.get("arrival_time"),
                    "departure_time": row.get("departure_time"),
                    "route_id": tl_trip_routes[trip_id],
                })
                used_stops.add(row.get("stop_id"))
                total += 1
                if len(batch) >= 50_000:
                    session.execute(stop_stmt, batch)
                    batch.clear()
            if batch:
                session.execute(stop_stmt, batch)
        log.info("Horaires théoriques importés : %d lignes (arrêts x courses)",
                 total)

        # Arrêts et lignes
        stop_rows = [{"stop_id": row.get("stop_id"),
                      "stop_name": row.get("stop_name"),
                      "stop_lat": float(row.get("stop_lat") or 0),
                      "stop_lon": float(row.get("stop_lon") or 0)}
                     for row in csv.DictReader(reader("stops.txt"))
                     if row.get("stop_id") in used_stops]
        with Session_factory.begin() as session:
            session.execute(Stop.__table__.insert().prefix_with("OR REPLACE"),
                            stop_rows)
            session.execute(TlRoute.__table__.insert().prefix_with("OR REPLACE"),
                            tl_route_rows)
            session.merge(MetaKV(key="static_feed_version",
                                 value=feed_version or "?"))
            session.merge(MetaKV(key="static_imported_at", value=utcnow_iso()))
        log.info("Import terminé : %d lignes, %d arrêts TL.",
                 len(tl_route_rows), len(stop_rows))
    return True


def ensure_static(Session_factory, http, gtfs_url=None, force=False,
                  api_key=None):
    """S'assure qu'un GTFS statique est en base ; retourne les filtres TL."""
    if not force and get_meta(Session_factory, "static_feed_version"):
        return load_tl_maps(Session_factory)
    tmp = tempfile.mktemp(suffix=".zip")
    try:
        if gtfs_url and not gtfs_url.startswith("http"):
            import_static_zip(Session_factory, gtfs_url)
        else:
            _, url = ((None, gtfs_url) if gtfs_url
                      else find_gtfs_static_url(http, api_key))
            download_file(http, url, tmp)
            import_static_zip(Session_factory, tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return load_tl_maps(Session_factory)
