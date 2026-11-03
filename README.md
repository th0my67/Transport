# tl-delay-collector

Collecteur des retards des bus/métro des **TL** (Transports publics de la région
lausannoise), à partir de la plateforme nationale
[opentransportdata.swiss](https://opentransportdata.swiss).

Il interroge le flux **GTFS Realtime « Trip Updates »** toutes les 30 secondes,
ne garde que les courses des lignes TL, et construit **l'historique des retards**
dans une base de données locale (la plateforme elle-même n'historise rien).

## Fonctionnement

1. **Import de l'horaire théorique** : télécharge le GTFS statique national,
   détecte l'agence TL dans `agency.txt`, et importe dans la base :
   - `tl_routes` : les lignes TL
   - `stops` : les arrêts utilisés par les TL
   - `stop_times` : l'horaire théorique (passage prévu de chaque course à chaque arrêt)
2. **Collecte temps réel** : interroge le flux GTFS-RT en boucle et enregistre,
   pour chaque course TL observée :
   - `stop_delays` : le retard à chaque arrêt — première observation (`first_*_delay`)
     et dernière observation (`last_*_delay`, qui se rapproche de l'arrivée réelle
     au fur et à mesure que le véhicule approche)
   - `trip_status` : statut de la course (annulée, véhicule, nombre de mises à jour)
   - `poll_log` : journal de chaque requête (succès/erreur, durée, volumétrie) pour
     vérifier la qualité de la collecte
3. **Rafraîchissement automatique** : le GTFS statique est re-téléchargé toutes les
   24 h, car les identifiants de courses changent chaque lundi et jeudi à 15h00.

## Prérequis

- Python **3.10+**
- Les paquets `requests` et `SQLAlchemy >= 2.0` (installés automatiquement avec le projet)
- Une **clé API gratuite** opentransportdata.swiss

## 1. Obtenir une clé API

1. Créez un compte sur <https://opentransportdata.swiss> (inscription gratuite).
2. Connectez-vous à l'**API-Manager**, section **« Default Key »**.
3. Copiez la clé générée.

> ⚠️ Ne commitez **jamais** cette clé dans Git. Utilisez une variable
> d'environnement ou un fichier `.env` (déjà ignoré par `.gitignore`).

## 2. Installation

```bash
git clone https://github.com/th0my67/Transport.git
cd Transport
python3 -m venv .venv && source .venv/bin/activate
pip install .                 # installe la commande `tl-delay-collector`
# ou, pour contribuer / lancer les tests :
pip install -e ".[dev]"
```

## 3. Configuration de la clé API

```bash
# Option recommandée : variable d'environnement
export OTD_API_KEY="votre-cle"

# ou fichier .env à la racine (non commité)
echo 'OTD_API_KEY="votre-cle"' > .env
set -a; source .env; set +a
```

La clé peut aussi être passée ponctuellement avec `--api-key "..."` (évitez :
elle reste visible dans l'historique du shell).

## 4. Utilisation

### a) Vérifier que tout fonctionne (recommandé en premier)

```bash
tl-delay-collector --dry-run
```

Une seule requête GTFS-RT est faite, puis le programme s'arrête. Vérifiez dans
les logs que des **courses TL** sont bien détectées (« … courses TL ») et que des
lignes TL apparaissent (« Lignes TL observées : 1, 2, … »).

### b) Importer uniquement l'horaire théorique

```bash
tl-delay-collector --import-only
```

Utile pour préparer la base sans consommer de quota API. Si aucune ligne TL
n'est détectée, le log affiche la liste des entreprises trouvées dans
`agency.txt` : ajustez alors `AGENCY_NAME_HINTS` / `ROUTE_ID_PREFIXES` dans
`src/tl_delay_collector/config.py`.

### c) Lancer la collecte

```bash
# collecte pendant 14 jours (défaut), base SQLite locale
tl-delay-collector --db tl_delays.db --days 14

# collecte infinie (jusqu'à Ctrl-C / SIGTERM, arrêt propre)
tl-delay-collector --days 0
```

Le programme tourne en boucle, interroge le flux **toutes les 30 secondes**
(par défaut), et s'arrête proprement sur `Ctrl-C`.

### Toutes les options

| Option | Défaut | Description |
|---|---|---|
| `--db` | `tl_delays.db` | Fichier SQLite, ou URL SQLAlchemy complète (ex. `postgresql+psycopg://tl:secret@localhost/tl_delays`) |
| `--api-key` | `$OTD_API_KEY` | Clé API opentransportdata.swiss |
| `--interval` | `30` | Secondes entre deux requêtes (minimum 12, limite plateforme) |
| `--days` | `14` | Durée de collecte en jours (`0` = infini) |
| `--log-file` | `tl_collector.log` | Fichier de log (rotation automatique) |
| `--gtfs-url` | auto | URL ou chemin local d'un ZIP GTFS statique, si le téléchargement auto échoue |
| `--static-refresh-hours` | `24` | Périodicité de re-téléchargement du GTFS statique |
| `--dry-run` | — | Une seule requête puis arrêt |
| `--import-only` | — | Importe le GTFS statique puis s'arrête |
| `--verbose` | — | Logs détaillés (DEBUG) |

## 5. Exploiter les données

Toutes les tables sont requêtables en SQL ou via pandas/SQLAlchemy :

```python
import pandas as pd
from sqlalchemy import create_engine, select
from tl_delay_collector.models import StopDelay, TripStatus, StopTime, TlRoute

engine = create_engine("sqlite:///tl_delays.db")

# Retards moyens par ligne TL
df = pd.read_sql(select(StopDelay.route_id,
                         StopDelay.last_arr_delay).where(
                             StopDelay.last_arr_delay.is_not(None)), engine)
df.groupby("route_id")["last_arr_delay"].mean() / 60   # minutes de retard moyen

# Courses annulées
pd.read_sql(select(TripStatus).where(TripStatus.ever_canceled == 1), engine)

# Qualité de la collecte : taux d'erreurs des polls
pd.read_sql("SELECT ok, COUNT(*) FROM poll_log GROUP BY ok", engine)
```

Schéma des tables :

| Table | Contenu |
|---|---|
| `stop_delays` | Retard par course/arrêt : `first_arr_delay`, `last_arr_delay`, `first_dep_delay`, `last_dep_delay`, `n_updates`… (clé : `start_date`, `trip_id`, `stop_sequence`) |
| `trip_status` | Dernière observation du statut de chaque course TL (clé : `start_date`, `trip_id`) |
| `stop_times` | Horaire théorique d'un arrêt pour une course (clé : `trip_id`, `stop_sequence`) |
| `stops` | Arrêts TL (nom, lat/lon) |
| `tl_routes` | Lignes TL détectées |
| `poll_log` | Journal de chaque requête GTFS-RT (ok, statut HTTP, volumétrie, durée, erreur) |
| `meta` | Clés/valeurs internes (version du GTFS importé, date d'import) |

## 6. Faire tourner en continu (service)

Exemple d'unité systemd `/etc/systemd/tl-collector.service` :

```ini
[Unit]
Description=Collecteur de retards TL
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/tl-delay-collector
EnvironmentFile=/opt/tl-delay-collector/.env
ExecStart=/opt/tl-delay-collector/.venv/bin/tl-delay-collector --db /var/lib/tl-collector/tl_delays.db --days 0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tl-collector
journalctl -u tl-collector -f     # suivre les logs
```

Sans systemd : `nohup tl-delay-collector --days 0 > collector.out 2>&1 &`

## 7. Limites et remarques

- Le flux GTFS-RT est limité à **5 requêtes/minute et par clé** : l'intervalle
  minimum est donc de 12 s (30 s par défaut, marge confortable).
- La plateforme **n'historise pas** les retards : laissez le collecteur tourner
  pendant toute la durée de l'étude pour construire l'historique.
- Les identifiants de courses changent chaque lundi/jeudi à 15h00 : le GTFS
  statique est re-téléchargé automatiquement toutes les 24 h.
- Les upserts utilisent la clause SQLite `ON CONFLICT DO UPDATE` ; avec un autre
  backend (PostgreSQL), remplacez les `sqlite_insert` dans `repository.py` par
  l'insert du dialecte correspondant.

## 8. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Aucune course TL dans ce poll » | Mauvais filtre agence | Lancez `--import-only`, lisez la liste des entreprises, ajustez `AGENCY_NAME_HINTS` dans `config.py` |
| Erreur HTTP 401 | Clé API invalide/expirée | Vérifiez `OTD_API_KEY` (le collecteur s'arrête alors volontairement) |
| Échec de téléchargement du GTFS statique | CKAN indisponible | Relancez avec `--gtfs-url /chemin/GTFS.zip` téléchargé manuellement sur <https://opendata.swiss> |
| Base vide après plusieurs heures | Pas de trafic TL à cette heure | Normal la nuit ; vérifiez `poll_log` (`SELECT ok, COUNT(*) FROM poll_log GROUP BY ok`) |

## 9. Structure du projet

```
src/tl_delay_collector/
├── cli.py           # point d'entrée CLI (argparse) et orchestration
├── collector.py     # boucle de collecte, dry-run, signaux, backoff, logs
├── config.py        # constantes et réglages (URLs, intervalles, hints agence TL)
├── db.py            # moteur SQLAlchemy (SQLite par défaut, PostgreSQL via URL)
├── models.py        # modèles ORM (les tables documentées ci-dessus)
├── repository.py    # accès aux données : filtres TL, upserts, poll_log, meta
├── gtfs_static.py   # découverte CKAN, téléchargement et import du GTFS statique
├── gtfs_rt.py       # requête et parsing du flux GTFS-RT
└── utils.py         # petits outils (dates, JSON à graphies multiples, conversions)
tests/               # tests unitaires hors réseau (pytest)
```

## 10. Tests

```bash
pip install -e ".[dev]"
pytest
```

## Licence

MIT
