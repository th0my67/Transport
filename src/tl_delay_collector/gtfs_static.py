import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

import requests

from .config import (AGENCY_NAME_HINTS, CKAN_BASE, GTFS_DATASET_CANDIDATES,
                     ROUTE_ID_PREFIXES)
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


def find_gtfs_static_url(http):
    """Trouve l'URL du dernier ZIP GTFS statique via l'API CKAN."""
    for dataset in GTFS_DATASET_CANDIDATES:
        try:
            r = http.get(f"{CKAN_BASE}/api/3/action/package_show",
                         params={"id": dataset}, timeout=60)
            if not r.ok:
                continue
            payload = r.json()
            if not payload.get("success"):
                continue
            resources = payload.get("result", {}).get("resources", [])
            zips = sorted(str(res["url"]) for res in resources
                         if str(res.get("url", "")).endswith(".zip"))
            if zips:
                return dataset, zips[-1]
        except requests.RequestException as exc:
            log.warning("CKAN %s indisponible : %s", dataset, exc)
    raise RuntimeError(
        "Impossible de trouver le GTFS statique automatiquement. Téléchargez "
        "le ZIP sur https://opendata.swiss (recherche : « horaire GTFS2020 »), "
        "puis relancez avec --gtfs-url /chemin/vers/GTFS.zip"
    )


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


def ensure_static(Session_factory, http, gtfs_url=None, force=False):
    """S'assure qu'un GTFS statique est en base ; retourne les filtres TL."""
    if not force and get_meta(Session_factory, "static_feed_version"):
        return load_tl_maps(Session_factory)
    tmp = tempfile.mktemp(suffix=".zip")
    try:
        if gtfs_url and not gtfs_url.startswith("http"):
            import_static_zip(Session_factory, gtfs_url)
        else:
            _, url = (None, gtfs_url) if gtfs_url else find_gtfs_static_url(http)
            download_file(http, url, tmp)
            import_static_zip(Session_factory, tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return load_tl_maps(Session_factory)
