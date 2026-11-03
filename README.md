# tl-delay-collector

Collecte des retards des bus/métro des **TL** (Transports publics de la région
lausannoise) à partir de la plateforme nationale
[opentransportdata.swiss](https://opentransportdata.swiss).

Principe :

1. Télécharge le GTFS statique (horaire théorique) et isole les courses TL.
2. Interroge le flux GTFS Realtime « Trip Updates » (variante JSON) à intervalle
   régulier et n'enregistre que les courses TL.
3. Stocke tout dans la base (SQLite par défaut, PostgreSQL possible) :
   - `stop_delays` : retard par course/arrêt (1re et dernière observation)
   - `trip_status` : statut par course (annulée, ajoutée, véhicule...)
   - `stop_times` / `stops` / `tl_routes` : horaire théorique des TL
   - `poll_log` : journal des requêtes (qualité de la collecte)

## Installation

```bash
pip install .            # ou : pip install -e ".[dev]" pour les tests
```

Prérequis : Python 3.10+, `requests` et `SQLAlchemy >= 2.0`, plus une clé API
gratuite sur <https://opentransportdata.swiss> (API-Manager -> « Default Key »).

## Utilisation

```bash
# 1) test : une seule requête, vérifie la détection des lignes TL
export OTD_API_KEY="eyJ..."
tl-delay-collector --dry-run

# 2) collecte pendant 14 jours (par défaut)
tl-delay-collector --db /var/lib/tl-collector/tl_delays.db --days 14

# 3) importer uniquement l'horaire théorique (sans collecte)
tl-delay-collector --import-only
```

Le backend par défaut est SQLite (fichier local) ; pour PostgreSQL, passez une
URL SQLAlchemy complète via `--db`, par ex. :
`--db postgresql+psycopg://tl:secret@localhost/tl_delays`

Notes :

- Le flux GTFS-RT est limité à 5 requêtes/minute et par clé ; l'intervalle
  minimal est donc 12 s (30 s par défaut).
- Le GTFS statique est re-téléchargé automatiquement toutes les 24 h car les
  identifiants de courses changent chaque lundi et jeudi à 15h00.
- La plateforme n'historise PAS les retards : c'est ce collecteur qui construit
  l'historique, d'où la nécessité de le laisser tourner pendant l'étude.
- Les upserts massifs utilisent la clause SQLite « ON CONFLICT DO UPDATE » ;
  en changeant de backend, remplacez les `sqlite_insert` par l'insert du
  dialecte correspondant (la structure du code reste identique).

## Structure du projet

```
src/tl_delay_collector/
├── cli.py           # point d'entrée CLI (argparse) et orchestration
├── collector.py     # boucle de collecte, dry-run, logging
├── config.py        # constantes et réglages
├── db.py            # moteur SQLAlchemy (SQLite/PostgreSQL)
├── models.py        # modèles ORM (tables)
├── repository.py    # accès aux données : filtres TL, upserts, poll_log, meta
├── gtfs_static.py   # téléchargement et import du GTFS statique
├── gtfs_rt.py       # requête et parsing du flux GTFS-RT
└── utils.py         # petits outils (dates, JSON hétérogène, conversions)
tests/               # tests unitaires hors réseau (pytest)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
