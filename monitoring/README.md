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
| `parking_operations_total` | `operation="payment"`, `outcome` ∈ `requested`, `replayed`, `conflict`, `retried`, `accepted`, `refused` | Demandes de paiement : créées, rejouées, en conflit, représentées, acceptées, refusées |
| | `operation="transaction"`, `outcome` ∈ `accepted`, `refused` | Résultat de chaque tentative auprès de la passerelle |
| `process_*`, `python_info` | | Mémoire, CPU, descripteurs du processus |

Toutes les séries métier existent dès le démarrage, à 0. `/metrics` est public, comme `/health` :
il ne contient que des compteurs, aucune donnée de paiement.

## Démarrer

1. Renseigner les hôtes Render des camarades dans `prometheus/prometheus.yml` (jobs `booking`,
   `access`, `pricing` : hôte seul, sans `https://`). Les cibles laissées en `*-HOST` restent `DOWN`.
2. Lancer le service en local (port 8000), pour la cible `payment-local` :
   ```bash
   uvicorn app.main:create_app --factory --port 8000   # depuis la racine du dépôt
   ```
3. Lancer la supervision :
   ```bash
   cd monitoring
   docker compose up -d --build
   ```
4. Ouvrir http://localhost:9090/targets : chaque service est `UP` ou `DOWN`.

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
| Requêtes HTTP par seconde | `sum by (job) (rate(http_requests_total{route!="/metrics"}[1m]))` |
| Erreurs HTTP par seconde | `sum by (job, status) (rate(http_requests_total{outcome="error"}[5m]))` |
| Opérations métier (5 min) | `sum by (job, operation, outcome) (increase(parking_operations_total[5m]))` |

`route!="/metrics"` retire les collectes de Prometheus du trafic affiché. Les autres services
peuvent nommer leurs labels autrement (`code` au lieu de `status`…) : vérifier leur `/metrics`
avant d'adapter les requêtes.

Pour faire bouger les compteurs : `BASE_URL=http://localhost:8000 ./scripts/requests.sh`, ou les
boutons de http://localhost:8000/ui (un lot de 20, un refus de démonstration).

## Limites

- Collecter un service Render toutes les 15 s l'empêche de s'endormir : il consomme alors les
  heures gratuites de Render en continu. Ne laisser tourner la supervision que le temps des
  démonstrations (`docker compose down`).
- Prometheus et Grafana tournent en local : les données restent sur la machine (volumes Docker).
