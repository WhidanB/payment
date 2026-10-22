# Journal de travail — Payment

## 2 septembre

### Fait

- Lecture du cadrage métier et définition du périmètre : seul le service `payment` est concerné.
- Décisions de conception : une demande de paiement (clé d'idempotence fournie par l'appelant) agrège 1..N transactions (tentatives), statuts PENDING / ACCEPTED / REFUSED.
- Choix techniques : Python + FastAPI, architecture hexagonale, persistance en mémoire derrière un port, passerelle simulée (5 % de refus) en attendant Stripe.
- Implémentation complète du backend en architecture hexagonale (domain / application / adapters), un commit par étape.
- Règles métier : PENDING pendant 15 s (résolution asynchrone), 1 retry automatique après un refus, résultat récupéré par polling.
- Idempotence : un rejeu de la même clé renvoie la demande existante (200), sans nouvelle transaction ni nouvel encaissement ; verrou par clé pour les appels concurrents.
- UUID v7 (uuid-utils) pour les demandes et les transactions ; montants en centimes (entiers).
- API REST : POST /payments, GET /payments/{id}, /health, Swagger auto (/docs, /redoc, /openapi.json).
- Logs JSON structurés : un événement par changement d'état (payment.requested, transaction.created, transaction.refused, payment.retry_scheduled, payment.accepted…).
- 14 tests (idempotence, flux nominal, refus puis retry, e2e HTTP) avec gateway forcée et scheduler manuel, sans sleep.
- Déploiement sur Render (render.yaml, /health, un seul worker), vérifié en production : cycle POST → polling → ACCEPTED, rejeu 200, 422, 404, /docs.
- Script d'exploration manuelle `scripts/requests.sh`.

### Problèmes

- Premier build Render en échec : Python 3.14 par défaut, pas de wheel `pydantic-core` précompilé et compilation Rust impossible (système en lecture seule). La variable `PYTHON_VERSION` du blueprint était ignorée ; résolu avec un fichier `.python-version` (3.12.8).
- Environnement de dev sans `pip` ni `venv` : pip amorcé via `get-pip.py` dans un `.venv` créé avec `--without-pip`.

### Suite

- Valider le contrat d'API avec Booking et Access.
- Persistance Postgres et reprise des transactions PENDING au démarrage.
- Adapter Stripe.

## 3 septembre

### Fait

- Rédaction de `docs/ETAT_DU_SERVICE.md` : périmètre métier, modèle de données, contrat d'API, comportement, architecture, configuration, tests, déploiement, limites connues.
- Réponses aux 12 questions de cadrage du service (responsabilité, données possédées et interdites, appelants, événements, workflow dépendant, problème technique : idempotence + cycle de vie asynchrone).

### Problèmes

- Aucun.

### Suite

- Écrire le guide d'intégration pour Booking et Access.
- Valider le contrat d'API avec leurs équipes.

## 22 octobre

### Fait

#### Intégration
- Guide d'intégration `docs/INTEGRATION_BOOKING_ACCESS.md` pour Booking et Access : requêtes exactes pour les deux scénarios (réservation → BOOKING, sortie → PARKING_EXIT), statut → action (confirmer la réservation / ouvrir la barrière), recette de polling (2 s, budget 40 s), convention de clé d'idempotence, tableau d'erreurs.
- Exemples du guide validés en production (202).
- Message prêt à envoyer aux deux équipes (URL, lien du guide, clé, exemple curl).

#### Sécurité
- Convention commune proposée par Access : en-tête `X-API-Key`, une clé par service, /health ouvert, clés échangées en privé, activation coordonnée.
- Implémentation côté `payment` : dépendance FastAPI `APIKeyHeader` sur /payments, bouton Authorize dans Swagger, 401 si clé absente ou fausse.
- Inactive tant que `PAYMENT_API_KEY` n'est pas défini : aucun appelant existant n'est cassé, l'activation se fait au moment voulu dans le dashboard Render.
- `render.yaml` : variable déclarée en `sync: false` (jamais dans Git).
- 5 nouveaux tests (19 au total), `scripts/requests.sh` accepte `API_KEY`.

#### Documentation
- Confirmation du choix `amount` en `int` (centimes) plutôt que `float` : arithmétique exacte, même convention que Stripe.
- README mis à jour (statut, authentification, configuration) et ce journal réécrit.

### Problèmes

- Aucun bloquant. À noter : le push déclenche le redéploiement Render, mais l'activation de la clé est une étape distincte (variable d'environnement).

### Suite

- Activer `PAYMENT_API_KEY` sur Render après avoir prévenu Booking et Access, puis tester ensemble.
- Valider le contrat d'API avec Booking et Access (payload, génération de la clé d'idempotence).
- Persistance Postgres et reprise des transactions PENDING au démarrage (lève aussi la contrainte du worker unique).
- Adapter Stripe.
- Optionnel : CI (GitHub Actions), événements PaymentAccepted / PaymentRefused pour éviter le polling.
