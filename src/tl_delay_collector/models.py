from typing import Optional

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MetaKV(Base):
    """Petite table clé/valeur (version du GTFS statique importé, etc.)."""
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)


class TlRoute(Base):
    """Ligne TL (importée du GTFS statique)."""
    __tablename__ = "tl_routes"

    route_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agency_id: Mapped[Optional[str]] = mapped_column(Text)
    route_short_name: Mapped[Optional[str]] = mapped_column(Text)
    route_long_name: Mapped[Optional[str]] = mapped_column(Text)
    route_type: Mapped[Optional[int]] = mapped_column(Integer)


class Stop(Base):
    """Arrêt utilisé par les TL (importé du GTFS statique)."""
    __tablename__ = "stops"

    stop_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stop_name: Mapped[Optional[str]] = mapped_column(Text)
    stop_lat: Mapped[Optional[float]] = mapped_column(Float)
    stop_lon: Mapped[Optional[float]] = mapped_column(Float)


class StopTime(Base):
    """Horaire théorique : passage prévu d'une course à un arrêt."""
    __tablename__ = "stop_times"

    trip_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_id: Mapped[Optional[str]] = mapped_column(Text)
    arrival_time: Mapped[Optional[str]] = mapped_column(Text)
    departure_time: Mapped[Optional[str]] = mapped_column(Text)
    route_id: Mapped[Optional[str]] = mapped_column(Text, index=True)


class TripStatus(Base):
    """Statut temps réel d'une course TL (dernière observation)."""
    __tablename__ = "trip_status"

    start_date: Mapped[str] = mapped_column(Text, primary_key=True)
    trip_id: Mapped[str] = mapped_column(Text, primary_key=True)
    route_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(Text)
    schedule_relationship: Mapped[Optional[str]] = mapped_column(Text)
    ever_canceled: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[Optional[str]] = mapped_column(Text)
    last_seen: Mapped[Optional[str]] = mapped_column(Text)
    n_updates: Mapped[int] = mapped_column(Integer, default=1)


class StopDelay(Base):
    """Retard d'une course TL à un arrêt donné (1re et dernière observation).

    first_*_delay = retard au premier poll où la course est apparue dans le flux ;
    last_*_delay  = dernier retard non-nul observé (approximation de l'arrivée
    effective, la prévision s'affinant au fur et à mesure que le bus approche).
    """
    __tablename__ = "stop_delays"

    start_date: Mapped[str] = mapped_column(Text, primary_key=True)
    trip_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    stop_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    stop_rel: Mapped[Optional[str]] = mapped_column(Text)
    first_seen: Mapped[Optional[str]] = mapped_column(Text)
    last_seen: Mapped[Optional[str]] = mapped_column(Text)
    first_arr_delay: Mapped[Optional[int]] = mapped_column(Integer)
    last_arr_delay: Mapped[Optional[int]] = mapped_column(Integer)
    first_dep_delay: Mapped[Optional[int]] = mapped_column(Integer)
    last_dep_delay: Mapped[Optional[int]] = mapped_column(Integer)
    n_updates: Mapped[int] = mapped_column(Integer, default=1)


class PollLog(Base):
    """Journal des requêtes GTFS-RT (pilotage et qualité de la collecte)."""
    __tablename__ = "poll_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[Optional[str]] = mapped_column(Text, index=True)
    feed_ts: Mapped[Optional[str]] = mapped_column(Text)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    n_entities: Mapped[Optional[int]] = mapped_column(Integer)
    n_tl: Mapped[Optional[int]] = mapped_column(Integer)
    n_stop_updates: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
