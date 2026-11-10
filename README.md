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

## 6. Reproductibilité de l'étude (collecte sur 2 semaines)

Cette section décrit la procédure complète pour reproduire une étude de
ponctualité des lignes TL sur **14 jours**, à intervalle régulier, de manière
entièrement rejouable par un tiers.

### 6.1 Prérequis

1. Compte gratuit sur <https://opentransportdata.swiss> + clé dans l'**API Manager**
   (voir §1 et §3). **Deux produits doivent être activés** pour la procédure
   entièrement automatique :
   - **GTFS-RT** (obligatoire : flux temps réel, `Authorization: Bearer <clé>`) ;
   - **CKAN-API** (optionnel : permet au collecteur de trouver et télécharger
     seul le GTFS statique via `https://api.opentransportdata.swiss/ckan-api`).
   Sans CKAN-API, téléchargez le ZIP à la main sur
   <https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020>
   (ressource `GTFS_FP2026_*.zip` la plus récente) et passez `--gtfs-url`.
2. Environnement identique : Python 3.10+, `pip install -e ".[dev]"`, code à un
   commit donné (notez le hash `git rev-parse HEAD` dans votre rapport).

### 6.2 Préparation de la base (une fois)

```bash
export OTD_API_KEY="votre-cle"
tl-delay-collector --import-only            # importe l'horaire théorique TL
tl-delay-collector --dry-run                # 1 requête de contrôle
```

Vérifiez dans les logs : « Lignes TL détectées : N » et « … courses TL » > 0.
La base `tl_delays.db` contient alors `tl_routes`, `stops`, `stop_times` et
`meta.static_feed_version` (voir §5 pour le schéma complet).

### 6.3 Collecte sur 14 jours à intervalle régulier

```bash
# 14 jours, un poll toutes les 30 s, base dédiée à l'étude
tl-delay-collector --db tl_delays.db --interval 30 --days 14
```

- **Intervalle** : 30 s par défaut. La plateforme limite à **5 requêtes/min
  et par clé** ; le minimum supporté est donc 12 s (`--interval` est borné à
  12 s). À 30 s, on consomme 2 requêtes/min — marge confortable.
- **Volume attendu** : 14 j × 2 880 polls/j ≈ **40 320 requêtes**. Vérifiez en
  fin de collecte :
  ```sql
  SELECT ok, COUNT(*) FROM poll_log GROUP BY ok;      -- quasi tout à ok=1
  SELECT COUNT(*) FROM poll_log;                      -- ≈ 40320
  SELECT MIN(ts), MAX(ts) FROM poll_log;              -- plage de 14 jours
  ```
- **Lancement en arrière-plan** : `nohup tl-delay-collector --days 14 \
  > collector.out 2>&1 &` ou service systemd (§7). `Ctrl-C`/SIGTERM arrête
  proprement ; les données déjà enregistrées sont conservées.
- **Journal** : chaque requête est tracée dans `poll_log` (statut HTTP,
  durée, volumétrie, erreur) et dans `tl_collector.log` — gardez ces deux
  fichiers avec la base pour l'audit.

### 6.4 Rafraîchissement de l'horaire théorique

Le GTFS statique est re-téléchargé automatiquement toutes les 24 h
(`--static-refresh-hours`). Les identifiants de courses changent chaque
**lundi et jeudi à 15h00** : la version du feed est stockée dans
`meta.static_feed_version` ; une version identique n'est pas réimportée.
Si le téléchargement auto échoue en cours de collecte, le collecteur
continue avec l'horaire en base et réessaie 1 h plus tard.

### 6.5 Ce qui est enregistré à chaque poll

Pour chaque entité du flux GTFS-RT « Trip Updates » correspondant à une
course TL (§5) :

- `trip_status` : statut de la course (annulée ou non, véhicule, nombre de
  mises à jour) — upsert, clé `(start_date, trip_id)` ;
- `stop_delays` : pour chaque arrêt de la course, les retards d'arrivée et
  de départ **à la première observation** (`first_arr_delay`,
  `first_dep_delay`) et **à la dernière** (`last_arr_delay`,
  `last_dep_delay` — la prévision s'affinant à l'approche du bus, c'est
  l'approximation de l'heure réelle) — upsert, clé
  `(start_date, trip_id, stop_sequence)`.

Les retards sont en **secondes** ; `start_date` est la date de service au
format `YYYYMMDD` (fuseau Europe/Zurich). La plateforme n'historise rien :
tout l'historique provient de vos polls.

### 6.6 Analyse type (exemple reproductible)

```python
import pandas as pd
from sqlalchemy import create_engine, select, func
from tl_delay_collector.models import StopDelay, TlRoute

engine = create_engine("sqlite:///tl_delays.db")
q = (select(StopDelay.route_id, TlRoute.route_short_name,
             func.avg(StopDelay.last_dep_delay).label("retard_moy_s"),
             func.count().label("n"))
     .join(TlRoute, TlRoute.route_id == StopDelay.route_id)
     .where(StopDelay.last_dep_delay.is_not(None))
     .group_by(StopDelay.route_id))
df = pd.read_sql(q, engine)
df["retard_moy_min"] = df["retard_moy_s"] / 60
print(df.sort_values("retard_moy_min", ascending=False))
```

### 6.7 Checklist de reproductibilité

- [ ] Même commit du code (`git rev-parse HEAD` noté)
- [ ] Même version de Python et des paquets (`pip freeze > requirements-lock.txt`)
- [ ] Clé API avec produits GTFS-RT (+ CKAN-API si auto) activés
- [ ] `--interval 30 --days 14` (ou valeurs explicitées dans le rapport)
- [ ] Base `tl_delays.db`, `tl_collector.log` et `poll_log` archivés ensemble
- [ ] `SELECT ok, COUNT(*) FROM poll_log GROUP BY ok` → taux d'erreur ~0

## 7. Faire tourner en continu (service)

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

## 8. Limites et remarques

- Le flux GTFS-RT est limité à **5 requêtes/minute et par clé** : l'intervalle
  minimum est donc de 12 s (30 s par défaut, marge confortable).
- La plateforme **n'historise pas** les retards : laissez le collecteur tourner
  pendant toute la durée de l'étude pour construire l'historique.
- Les identifiants de courses changent chaque lundi/jeudi à 15h00 : le GTFS
  statique est re-téléchargé automatiquement toutes les 24 h.
- Les upserts utilisent la clause SQLite `ON CONFLICT DO UPDATE` ; avec un autre
  backend (PostgreSQL), remplacez les `sqlite_insert` dans `repository.py` par
  l'insert du dialecte correspondant.

## 9. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Aucune course TL dans ce poll » | Mauvais filtre agence | Lancez `--import-only`, lisez la liste des entreprises, ajustez `AGENCY_NAME_HINTS` dans `config.py` |
| Erreur HTTP 401 | Clé API invalide/expirée | Vérifiez `OTD_API_KEY` (le collecteur s'arrête alors volontairement) |
| Échec de téléchargement du GTFS statique (HTTP 403 CKAN, ou « Access to this API has been disallowed ») | `data.opentransportdata.swiss/api/3/action` renvoie 403 aux clients non navigateur ; l'API officielle `https://api.opentransportdata.swiss/ckan-api` exige une clé dont le produit **CKAN-API** est activé dans l'API Manager (<https://api-manager.opentransportdata.swiss>) | Le collecteur interroge `api.opentransportdata.swiss/ckan-api` avec `--api-key` / `OTD_API_KEY` (recherche du dataset GTFS le plus récent, puis noms connus) ; en dernier recours, téléchargez le ZIP sur <https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020> et relancez avec `--gtfs-url /chemin/GTFS.zip` |
| Base vide après plusieurs heures | Pas de trafic TL à cette heure | Normal la nuit ; vérifiez `poll_log` (`SELECT ok, COUNT(*) FROM poll_log GROUP BY ok`) |

## 10. Structure du projet

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

## 11. Tests

```bash
pip install -e ".[dev]"
pytest
```

## Licence

MIT
