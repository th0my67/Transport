from sqlalchemy import create_engine, event

from .models import Base


def make_engine(db_spec: str):
    """Construit le moteur SQLAlchemy : chemin de fichier SQLite, ou URL
    complète (postgresql+psycopg://...) pour un vrai serveur."""
    if "://" in db_spec:
        url = db_spec
    else:
        url = f"sqlite:///{db_spec}"
    engine = create_engine(url, echo=False)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    Base.metadata.create_all(engine)
    return engine
