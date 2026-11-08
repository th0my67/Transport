import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import requests
from sqlalchemy import func, select

from .config import MIN_POLL_INTERVAL
from .gtfs_rt import feed_timestamp, poll_gtfs_rt
from .gtfs_static import ensure_static
from .models import StopDelay, TlRoute, TripStatus
from .repository import log_poll, record_feed
from .utils import db_size_mb, log, utcnow_iso


def setup_logging(log_file, verbose):
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=5_000_000,
                                            backupCount=2, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=handlers,
    )


def dry_run(Session_factory, http, api_key, tl_route_ids, tl_trip_routes):
    log.info("--- DRY RUN : une seule requête GTFS-RT ---")
    t0 = time.monotonic()
    feed = poll_gtfs_rt(http, api_key)
    n_entities, n_tl, n_rows = record_feed(Session_factory, feed, utcnow_iso(),
                                           tl_route_ids, tl_trip_routes)
    log.info("Requête OK en %.1f s : %d entités au total, %d courses TL, "
             "%d mises à jour d'arrêts enregistrées.",
             time.monotonic() - t0, n_entities, n_tl, n_rows)
    if n_tl == 0:
        log.warning("Aucune course TL dans ce poll ! Le filtre est peut-être "
                    "mauvais (AGENCY_NAME_HINTS / ROUTE_ID_PREFIXES).")
    with Session_factory() as session:
        names = dict(session.execute(
            select(TlRoute.route_id, TlRoute.route_short_name)).all())
        seen = {row[0] for row in session.execute(
            select(TripStatus.route_id).distinct())}
        log.info("Lignes TL observées : %s",
                 sorted({names.get(r, r) for r in seen}))
        examples = session.execute(
            select(StopDelay.start_date, StopDelay.route_id, StopDelay.trip_id,
                   StopDelay.stop_sequence, StopDelay.stop_id,
                   StopDelay.last_dep_delay, StopDelay.n_updates)
            .order_by(StopDelay.last_seen.desc()).limit(8)).all()
    for row in examples:
        log.info("Exemple : %s", tuple(row))
    log_poll(Session_factory, ok=1, n_entities=n_entities, n_tl=n_tl,
             n_rows=n_rows, duration_ms=(time.monotonic() - t0) * 1000,
             feed_ts=feed_timestamp(feed))


def run_collection(Session_factory, http, api_key, args, tl_route_ids,
                   tl_trip_routes):
    """Boucle de collecte principale (jusqu'à --days ou signal d'arrêt)."""
    stop = {"flag": False}

    def on_signal(signum, _frame):
        log.info("Signal %s reçu, arrêt propre...", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    interval = max(args.interval, MIN_POLL_INTERVAL)
    deadline = (datetime.now(timezone.utc) + timedelta(days=args.days)
                if args.days and args.days > 0 else None)
    next_refresh = datetime.now(timezone.utc) + timedelta(
        hours=args.static_refresh_hours or 24)
    backoff = 0.0
    polls = 0
    t_start = time.monotonic()

    while not stop["flag"]:
        now = datetime.now(timezone.utc)
        if deadline and now >= deadline:
            log.info("Durée de collecte atteinte (%s jours).", args.days)
            break

        # Rafraîchissement périodique du GTFS statique
        if now >= next_refresh:
            try:
                tl_route_ids, tl_trip_routes = ensure_static(
                    Session_factory, http, gtfs_url=args.gtfs_url, force=True,
                    api_key=api_key)
                next_refresh = now + timedelta(
                    hours=args.static_refresh_hours or 24)
            except Exception as exc:  # noqa: BLE001
                log.warning("Échec du rafraîchissement GTFS statique : %s "
                            "(nouvel essai dans 1 h)", exc)
                next_refresh = now + timedelta(hours=1)

        t0 = time.monotonic()
        try:
            feed = poll_gtfs_rt(http, api_key)
            elapsed = time.monotonic() - t0
            n_entities, n_tl, n_rows = record_feed(
                Session_factory, feed, utcnow_iso(), tl_route_ids,
                tl_trip_routes)
            log_poll(Session_factory, ok=1, n_entities=n_entities, n_tl=n_tl,
                     n_rows=n_rows, duration_ms=elapsed * 1000,
                     feed_ts=feed_timestamp(feed))
            polls += 1
            backoff = 0.0
            if polls % 120 == 0:  # statut ~horaire à 30 s d'intervalle
                with Session_factory() as session:
                    n_trips = session.scalar(
                        select(func.count()).select_from(TripStatus))
                    n_stops = session.scalar(
                        select(func.count()).select_from(StopDelay))
                log.info("Statut : %d polls | base %.1f Mo | courses TL "
                         "distinctes : %d | arrêts-courses : %d",
                         polls, db_size_mb(args.db), n_trips, n_stops)
            else:
                log.debug("Poll %d : %d entités, %d TL, %d arrêts.",
                          polls, n_entities, n_tl, n_rows)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            log_poll(Session_factory, ok=0, http_status=status,
                     duration_ms=(time.monotonic() - t0) * 1000, error=str(exc))
            if status == 401:
                log.error("Clé API refusée (401) : arrêt. Vérifiez OTD_API_KEY.")
                break
            log.warning("Erreur HTTP %s : %s", status, exc)
            backoff = min(backoff * 2 or 60, 600)
        except Exception as exc:  # noqa: BLE001
            log_poll(Session_factory, ok=0,
                     duration_ms=(time.monotonic() - t0) * 1000,
                     error=repr(exc))
            log.warning("Erreur : %r", exc)
            backoff = min(backoff * 2 or 60, 600)

        # Attente (interruptible) : respecte la limite de 5 requêtes/min
        wait = max(interval - (time.monotonic() - t0), MIN_POLL_INTERVAL)
        if backoff:
            wait = max(wait, backoff)
        end = time.monotonic() + wait
        while not stop["flag"] and time.monotonic() < end:
            time.sleep(1)

    hours = (time.monotonic() - t_start) / 3600
    log.info("=== Fin de collecte : %d polls en %.1f h | base %.1f Mo ===",
             polls, hours, db_size_mb(args.db))
    log.info("Analyse : requêtez les modèles ORM (StopDelay, TripStatus, "
             "StopTime, TlRoute) avec SQLAlchemy ou chargez-les avec pandas : "
             "pd.read_sql(select(...), engine).")
