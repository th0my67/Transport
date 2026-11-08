from zoneinfo import ZoneInfo

GTFS_RT_URL = "https://api.opentransportdata.swiss/la/gtfs-rt"
# API CKAN officielle (via l'API Manager ; data.opentransportdata.swiss
# renvoie HTTP 403 aux clients non navigateur sur /api/3/action).
CKAN_API_BASE = "https://api.opentransportdata.swiss/ckan-api"
# Jeux de données GTFS statiques de repli (recherche CKAN d'abord).
GTFS_DATASET_CANDIDATES = [
    "timetable-2027-gtfs2020",
    "timetable-2026-gtfs2020",
]
GTFS_SEARCH_QUERY = "timetable gtfs"
USER_AGENT = "tl-delay-collector/1.0 (etude ponctualite TL)"

# Détection des TL dans agency.txt : correspondance sur le nom de l'entreprise.
# Si aucune entreprise ne correspond, lancez --import-only une première fois :
# le script affiche la liste des entreprises trouvées, ajustez ensuite ces
# indices (ou ROUTE_ID_PREFIXES ci-dessous).
AGENCY_NAME_HINTS = ("lausannois", "transports publics lausannois")
# Repli : préfixes de route_id si la détection via agency.txt échoue
# (ex. ROUTE_ID_PREFIXES = ("92-",) ; à n'utiliser qu'après vérification).
ROUTE_ID_PREFIXES = ()

MIN_POLL_INTERVAL = 12          # limite plateforme : 5 requêtes/min
STATIC_REFRESH_HOURS = 24       # nouveaux horaires chaque lundi/jeudi 15h
UPSERT_CHUNK = 500              # lignes par statement (limite de variables SQLite)
ZURICH = ZoneInfo("Europe/Zurich")
