# Supervision — Prometheus et Grafana

Supervise `payment` et les autres microservices du projet Parking Management. Chaque service
supervisé doit exposer `GET /metrics` au format Prometheus.

| Outil | URL | Rôle |
|---|---|---|
| Prometheus | http://localhost:9090 | Collecte toutes les 15 s, requêtes PromQL, état des cibles |
| Grafana (bonus) | http://localhost:3000 | Tableau de bord « Parking — supervision des microservices » (lecture sans connexion, admin : `admin` / `admin` sauf `GRAFANA_ADMIN_PASSWORD`) |

## Fichiers

| Fichier | Contenu |
|---|---|
| `prometheus/Dockerfile` | Image officielle `prom/prometheus` (version fixée) + configuration |
| `prometheus/prometheus.yml` | Services surveillés (`scrape_configs`) |
| `compose.yaml` | Prometheus + Grafana |
| `grafana/` | Source de données et tableau de bord créés automatiquement au démarrage |

## Métriques exposées par `payment`

| Métrique | Labels | Sens |
|---|---|---|
| `http_requests_total` | `method`, `route` (gabarit, ex. `/payments/{payment_id}`), `status`, `outcome` (`success` si < 400, sinon `error`) | Requêtes HTTP traitées |
| `parking_operations_total` | `operation="payment"`, `result` ∈ `requested`, `replayed`, `conflict`, `retried`, `accepted`, `refused` | Demandes de paiement : créées, rejouées, en conflit, représentées, acceptées, refusées |
| | `operation="transaction"`, `result` ∈ `accepted`, `refused` | Résultat de chaque tentative auprès de la passerelle |
| `process_*`, `python_info` | | Mémoire, CPU, descripteurs du processus |

Toutes les séries métier existent dès le démarrage, à 0. `/metrics` est public, comme `/health` :
il ne contient que des compteurs, aucune donnée de paiement.

## Services surveillés

| Job | Cible | Particularité |
|---|---|---|
| `payment` | https://payment-xp8n.onrender.com/metrics | Notre service en production |
| `payment-local` | `host.docker.internal:8000` | Notre service lancé sur la machine |
| `booking` | https://booking-api-vhy5.onrender.com/v2/booking/metrics | Chemin propre (`metrics_path`) |
| `access` | https://access-api-a1u7.onrender.com/metrics | Protégé par `X-API-Key` |
| `parking` | https://parking-6r73.onrender.com/metrics | |
| `vehicles` | https://parking-vehicles.onrender.com/metrics | Spring Boot : métriques renommées à la collecte (voir plus bas) |

Les services ne nomment pas leurs labels de la même façon ; les requêtes plus bas fonctionnent
pour tous :

| Service | Route HTTP | Code HTTP | Résultat métier |
|---|---|---|---|
| payment | `route` | `status="202"` | `result` |
| booking | `route` | `status="409"` | `result` |
| parking | `path` | `status="200"` | `result` |
| access | `handler` | `status="2xx"` | `result` |
| vehicles | `uri`, copié en `route` | `status="200"` | aucun (`operation="vehicle_create"` seulement) |

**Vehicles.** Spring Boot n'expose ni `http_requests_total` ni `parking_operations_total`. Prometheus renomme
à la collecte (`metric_relabel_configs`) `http_server_requests_seconds_count` en `http_requests_total`
et `vehicles_creations_total` en `parking_operations_total{operation="vehicle_create"}` : les requêtes
et le tableau de bord le couvrent sans modification.

**Clé d'Access.** Prometheus l'envoie dans l'en-tête `X-API-Key`, lue dans
`prometheus/secrets/access_api_key` (ignoré par Git, monté en lecture seule). Sur une autre
machine, recréer ce fichier, lisible par le conteneur :
`printf '%s' '<clé>' > prometheus/secrets/access_api_key && chmod 644 prometheus/secrets/access_api_key`.

## Démarrer

1. Lancer le service en local (port 8000), pour la cible `payment-local` :
   ```bash
   .venv/bin/uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000   # depuis la racine du dépôt
   ```
2. Lancer la supervision :
   ```bash
   cd monitoring
   docker compose up -d --build
   ```
3. Ouvrir http://localhost:9090/targets : chaque service est `UP` ou `DOWN`.

Après une modification de `prometheus.yml`, recharger sans redémarrer :
`curl -X POST http://localhost:9090/-/reload`.

## Simuler l'indisponibilité d'un service

- **Service local** : arrêter uvicorn (Ctrl+C). Sous 15 s, `payment-local` passe `DOWN` dans
  `/targets` et `up{job="payment-local"}` tombe à 0. Le relancer : retour à `UP`.
- **Service Render** : une instance endormie met 30 à 50 s à se réveiller, plus que le délai de
  collecte (10 s). Elle apparaît `DOWN` puis remonte `UP` une fois réveillée.

## Les trois graphiques (onglet Graph de Prometheus)

| Graphique | PromQL |
|---|---|
| Disponibilité des services | `up{job!="prometheus"}` |
| Requêtes HTTP par seconde | `sum by (job) (rate(http_requests_total{route!~".*/metrics",path!~".*/metrics",handler!~".*/metrics"}[1m]))` |
| Erreurs HTTP par seconde | `sum by (job, status) (rate(http_requests_total{status=~"[45].*"}[5m]))` |
| Opérations métier (5 min) | `sum by (job, operation, result) (increase(parking_operations_total[5m]))` |

Le filtre sur `route` / `path` / `handler` retire les collectes de Prometheus du trafic affiché,
quel que soit le nom du label (un label absent vaut `""` et passe le filtre). `status=~"[45].*"`
reconnaît à la fois `404` et `4xx`.

Pour faire bouger les compteurs : `BASE_URL=http://localhost:8000 ./scripts/requests.sh`, ou les
boutons de http://localhost:8000/ui (un lot de 20, un refus de démonstration).

## Limites

- Collecter un service Render toutes les 15 s l'empêche de s'endormir : il consomme alors les
  heures gratuites de Render en continu. Ne laisser tourner la supervision que le temps des
  démonstrations (`docker compose down`).
- Prometheus et Grafana tournent en local : les données restent sur la machine (volumes Docker).
