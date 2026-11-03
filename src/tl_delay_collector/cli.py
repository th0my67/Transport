import argparse
import os
import sys

import requests
from sqlalchemy.orm import sessionmaker

from .collector import dry_run, run_collection, setup_logging
from .config import MIN_POLL_INTERVAL, STATIC_REFRESH_HOURS, USER_AGENT
from .db import make_engine
from .gtfs_static import ensure_static
from .utils import log


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tl-delay-collector",
        description="Collecte des retards des lignes TL (GTFS-RT, "
                    "opentransportdata.swiss) via SQLAlchemy.")
    parser.add_argument("--api-key", default=os.environ.get("OTD_API_KEY"),
                        help="Clé API (ou variable d'environnement OTD_API_KEY)")
    parser.add_argument("--db", default="tl_delays.db",
                        help="Fichier SQLite, ou URL SQLAlchemy complète "
                             "(postgresql+psycopg://...) ; défaut : tl_delays.db")
    parser.add_argument("--interval", type=int, default=30,
                        help="Secondes entre deux requêtes (défaut : 30 ; min : 12)")
    parser.add_argument("--days", type=float, default=14,
                        help="Durée de collecte en jours (défaut : 14 ; 0 = infini)")
    parser.add_argument("--log-file", default="tl_collector.log",
                        help="Fichier de log (défaut : tl_collector.log)")
    parser.add_argument("--gtfs-url", default=None,
                        help="URL (ou chemin local) du ZIP GTFS statique, si le "
                             "téléchargement automatique échoue")
    parser.add_argument("--static-refresh-hours", type=float,
                        default=STATIC_REFRESH_HOURS,
                        help="Rafraîchissement du GTFS statique en heures (défaut : 24)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Une seule requête puis arrêt (vérification)")
    parser.add_argument("--import-only", action="store_true",
                        help="Importe uniquement le GTFS statique puis arrêt")
    parser.add_argument("--verbose", action="store_true", help="Log détaillé")
    return parser


def main():
    args = build_parser().parse_args()

    setup_logging(args.log_file, args.verbose)
    interval = max(args.interval, MIN_POLL_INTERVAL)
    log.info("=== Collecteur de retards TL (SQLAlchemy) ===")
    log.info("Base : %s | intervalle : %ds | durée : %s jours",
             args.db, interval, args.days or "∞")

    http = requests.Session()
    http.headers.update({"User-Agent": USER_AGENT})
    engine = make_engine(args.db)
    Session_factory = sessionmaker(engine)

    # 1) Horaire théorique + filtres TL
    try:
        tl_route_ids, tl_trip_routes = ensure_static(
            Session_factory, http, gtfs_url=args.gtfs_url)
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(2)

    if args.import_only:
        log.info("Import seul demandé : terminé.")
        return

    api_key = args.api_key
    if not api_key:
        log.error("Clé API manquante : créez un compte sur "
                  "https://opentransportdata.swiss puis passez OTD_API_KEY "
                  "ou --api-key.")
        sys.exit(2)

    if args.dry_run:
        dry_run(Session_factory, http, api_key, tl_route_ids, tl_trip_routes)
        return

    # 2) Boucle de collecte
    run_collection(Session_factory, http, api_key, args,
                   tl_route_ids, tl_trip_routes)


if __name__ == "__main__":
    main()
