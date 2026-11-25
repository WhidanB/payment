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

## 18 novembre — matin

### Fait

- Jalon 8 (UI de démonstration et d'exploitation) : console `/ui`, une page HTML/CSS/JS vanilla servie par le service lui-même (pas de second déploiement, pas de CORS), `/` y redirige.
- Objets et états : liste des demandes (statut, montant, référence, appelant, tentatives, barre de progression du délai PENDING), compteurs par statut, détail d'une demande avec ses transactions (identifiant, tentative, statut, durée) et JSON brut.
- Opérations : création d'une demande, rejeu de la même requête (démonstration de l'idempotence : 200, même payment_id), lot de 20 paiements pour observer un refus suivi de son retry.
- Résultat des actions : journal des appels (code HTTP, résumé, requête et réponse dépliables), rafraîchissement automatique toutes les 2 s, bandeau explicite si la clé API manque (401).
- Contexte affiché : version, délai PENDING, tentatives max, taux de refus simulé, authentification active ou non, rappel du vocabulaire métier.
- Backend : nouvelle route `GET /payments?limit=` (liste, protégée par X-API-Key), `idempotency_key` ajouté à la réponse, `/health` expose la configuration utile à l'UI (champs additifs, contrat existant inchangé).
- Sécurité de l'UI : aucune donnée de l'API injectée en HTML (construction du DOM par `textContent`), clé API gardée en `sessionStorage` uniquement.
- 24 tests (5 nouveaux : liste, limite invalide, UI servie, redirection, clé API).
- Vérification dans un vrai navigateur (Chromium headless via Playwright) : création, rejeu (200), passage PENDING → ACCEPTED, lot de 20 avec refus et retry visibles, flux clé API (401 puis accès après saisie), aucune erreur JavaScript.

### Problèmes

- Première version : erreur JavaScript sur le journal du lot de 20 (champ absent dans la réponse agrégée), corrigée et revérifiée.
- Reconstruire le tableau à chaque rafraîchissement faisait perdre les clics sur une ligne : la liste n'est reconstruite que si les données changent, les barres de progression sont mises à jour sur place.
- Environnement sans navigateur ni bibliothèques système : Chromium et ses dépendances installés localement sans droits root, hors du dépôt.

### Suite

- Pousser et redéployer, puis vérifier `/ui` sur Render.
- Activer `PAYMENT_API_KEY` après avoir prévenu Booking et Access, puis tester ensemble.
- Persistance Postgres et reprise des transactions PENDING au démarrage.
- Optionnel : tests automatisés de l'UI, forcer un refus à la demande pour la démonstration.

## 18 novembre — après-midi

### Fait

Jalon 9 (qualité et fiabilité). Audit du comportement du service, puis corrections et preuves.

#### Entrées invalides
- Montant : entier strict de 1 à 10 000 000 centimes (`"1250"`, `12.5` et `true` n'étaient plus acceptés silencieusement), devise `EUR` déclarée dans le schéma, clé d'idempotence et identifiant de référence nettoyés, non vides et bornés (200 / 100 caractères).
- Réponses d'erreur documentées dans OpenAPI (401, 409, 422).

#### Cas limites corrigés
- Une clé d'idempotence réutilisée avec une requête différente renvoyait silencieusement l'ancienne demande : elle renvoie maintenant `409` et la demande d'origine reste intacte.
- Une exception de la passerelle (panne du prestataire) laissait la transaction en `PENDING` pour toujours : elle est journalisée et traitée comme un refus, donc le retry s'applique.
- Clé API comparée avec `hmac.compare_digest` (temps constant).

#### Logs exploitables
- `X-Request-ID` accepté, généré ou renvoyé, porté par toutes les lignes de log de la requête, y compris la résolution asynchrone 15 s plus tard.
- Une ligne `http.request` par appel (méthode, chemin, statut, durée), `/health` et la liste sondée par l'UI en `DEBUG` seulement, `500` JSON avec `request_id`, `PAYMENT_LOG_LEVEL`, logs d'accès uvicorn désactivés (remplacés par les nôtres en JSON).

#### Vérifiabilité
- 24 → 123 tests (131 après la démonstration du refus) : matrice d'entrées invalides, valeurs limites, conflits d'idempotence, 25 appels concurrents, panne du prestataire, double résolution, invariants du domaine, adapters, contenu des logs. Couverture de branches 99,7 % (seuil 90 %).
- Les trois garde-fous critiques (verrou par clé, capture des exceptions de la passerelle, détection de conflit) vérifiés par mutation : les désactiver fait échouer les tests.
- Outillage : `ruff` (lint, format, complexité cyclomatique ≤ 10), `requirements-dev.txt` séparé du runtime, workflow GitHub Actions, `scripts/verify.sh` (mêmes contrôles en local).
- Documentation à jour : `docs/VERIFICATION.md` (nouvelle : commande unique, cas testés, catalogue des logs, scénarios manuels, vérification en production), README, `ETAT_DU_SERVICE.md`, guide d'intégration (409, bornes, `X-Request-ID`).
- Vérifié de bout en bout : démarrage avec les seules dépendances runtime, logs réels corrélés par `request_id`, console `/ui` toujours fonctionnelle dans Chromium headless.

#### Démonstration du refus et de sa nouvelle présentation
- Constat en testant la console : avec 5 % de refus aléatoires, on ne voit presque jamais un paiement refusé puis représenté, et la liste n'affichait qu'un nombre de tentatives.
- La passerelle reçoit désormais le numéro de tentative et l'identifiant de transaction (ce dernier servira de clé d'idempotence côté Stripe). Comme les cartes de test Stripe, les références `demo-refuse-once…` (refus puis retry accepté) et `demo-refuse-always…` (refus définitif) donnent une issue garantie, y compris en production.
- Console `/ui` : boutons « Refus puis retry accepté » et « Refus définitif », chaîne des tentatives dans la liste (`REFUSED → PENDING`, puis `REFUSED → ACCEPTED`), récit dans le détail (« refusée à la tentative 1, représentée automatiquement, acceptée à la tentative 2 »), lien entre les tentatives, compteur des demandes représentées, bouton « Représenter ce paiement » après un refus définitif (nouvelle demande, nouvelle clé).
- 131 tests ; les trois parcours vérifiés dans Chromium headless, sans erreur JavaScript.

### Problèmes

- Les tests de logs passaient à vide (aucune sortie capturée) : le handler gardait une référence à un ancien `stdout`. Corrigé en résolvant `sys.stdout` à chaque écriture, et ajout d'une assertion « sortie non vide ».
- `ruff` a signalé des commentaires `noqa` inutiles et des lignes trop longues : corrigés, un passage de format sur tout le dépôt.
- Branche « règle violée après validation du schéma » de la route non atteignable par HTTP : conservée comme filet de sécurité, couverte au niveau du domaine.

### Suite

- Constater le passage de la CI GitHub Actions sur les commits poussés.
- Vérifier en production (Render) : `/ui`, les boutons de démonstration du refus, `X-Request-ID` et le `409`.
- Optionnel : `pip-audit` en CI, branch protection sur `master`, tests automatisés de l'UI.
- Activer `PAYMENT_API_KEY` après avoir prévenu Booking et Access ; persistance Postgres et reprise des `PENDING`.

## 24 novembre

### Fait

- Questions de revue : les actions utilisateurs sont-elles loggées (oui côté API, mais sans identité de l'appelant ni motif des `422` / `401`, et le journal de l'UI reste dans le navigateur), et quelle base de données (aucune : stockage en mémoire, perdu à chaque mise en veille de Render).
- Décision : base PostgreSQL serverless sur **Neon**, pour ne plus rien perdre quand Render s'endort.
- Adapter `PostgresPaymentRepository` (driver `asyncpg`), branché à la place du stockage en mémoire sans toucher au domaine (port `PaymentRepository`). Choix du stockage dans `container.py` selon `PAYMENT_DATABASE_URL`.
- Schéma créé au démarrage (verrou consultatif pour plusieurs instances) : `payment_requests` (clé d'idempotence **unique**, montant > 0) et `payment_transactions` (une ligne par tentative, unique par demande, index sur les `PENDING`). Écriture de l'agrégat dans une seule transaction SQL.
- Idempotence garantie par la base : si deux instances créent la même clé au même instant, la contrainte unique tranche et la seconde répond comme un rejeu (`200`) ou un conflit (`409`).
- Reprise après redémarrage : au démarrage, les transactions encore `PENDING` sont replanifiées pour le temps restant seulement, puis résolues normalement (retry compris).
- `/health` indique le stockage sans toucher la base (les sondes Render ne réveillent pas Neon) ; `/health?deep=true` vérifie la connexion (`degraded` si la base est injoignable). L'UI affiche le stockage utilisé.
- Réglages propres à Neon : pool sans connexion inactive durable (Neon suspend la base), cache de requêtes préparées désactivé (pooler), chaîne de connexion acceptée telle que copiée depuis Neon.
- `render.yaml` : `PAYMENT_DATABASE_URL` en `sync: false` (jamais dans Git) ; `.env.example` pour le local ; CI GitHub Actions avec un service Postgres 16.
- 131 → 163 tests : contrat commun aux deux stockages, survie à un redémarrage, reprise d'un `PENDING` interrompu, course entre deux instances, santé `degraded`, chaînes Neon. Couverture ~99 % avec base, 92 % sans. Garde-fous vérifiés par mutation (gestion de la course, reprise au démarrage).
- Vérifié avec un vrai serveur : service arrêté 2 s après la création d'un paiement, redémarré, transaction reprise pour les ~5,4 s restantes puis résolue (refus, retry, acceptation).
- Documentation mise à jour : README (section Neon, mise en place, configuration, limites, maturité), `ETAT_DU_SERVICE.md`, `VERIFICATION.md`, guide d'intégration.

### Problèmes

- Pas de Postgres ni de Docker sur la machine de développement : tests faits contre un Postgres 16 embarqué (`pgserver`, installé hors du projet) ; la CI utilise un conteneur Postgres.
- La chaîne de connexion fournie par Neon contient `channel_binding=require`, option propre à libpq qu'`asyncpg` transmet au serveur, qui la rejette : le service aurait planté au démarrage. Le paramètre est retiré avant la connexion (testé).
- Fixture de test asynchrone paramétrée qui démarrait la base dans une boucle déjà active : passée en fixture synchrone.

### Suite

- Créer le projet Neon, ajouter `PAYMENT_DATABASE_URL` dans Render, vérifier `/health?deep=true` (`storage: postgres`, `database: ok`), puis créer un paiement, attendre la mise en veille et vérifier qu'il est toujours là.
- Rester sur un seul worker : la résolution différée n'est pas coordonnée entre instances.
- Logs : identifier l'origine des actions (UI, appelant), motif des `422`, `401` en avertissement.
- Activer `PAYMENT_API_KEY` après avoir prévenu Booking et Access.


## 25 novembre

### Fait

- Questions de revue sur l'idempotence (clé fournie par l'appelant, contrainte unique en base, rôle des UUID), la génération des clés API et les logs.
- Constat dans les logs de production : Booking n'envoie aucun identifiant de corrélation (le `request_id` d'un de ses `GET` est un UUID v7 daté de l'arrivée de la requête, donc généré par nous).
- Décision commune : l'en-tête de corrélation de toute la chaîne est **`X-Correlation-ID`**. Le service le lit, le génère s'il manque, le renvoie et le porte dans chaque ligne de log (champ `correlation_id`, y compris la résolution 15 s plus tard et le corps des `500`). `X-Request-ID` n'est plus lu.
- Guide d'intégration, README, `ETAT_DU_SERVICE.md` et `VERIFICATION.md` mis à jour.
- Booking confirme que sa clé d'idempotence était déjà stable d'un essai à l'autre (suffixe tiré une fois par réservation) ; passage quand même à `booking:{reservation_id}:create`, codes de réservation plus jamais réattribués, `X-Correlation-ID` envoyé. Réponses apportées : clés sans expiration, rejeu en `200` quel que soit le statut, et un `409` ou un `401` ne prouvent pas qu'aucun paiement n'existe.
- Supervision (consigne Prometheus) : `GET /metrics` au format Prometheus, public comme `/health`. `http_requests_total` par méthode, gabarit de route (pas un compteur par identifiant de paiement), statut et `success` / `error` ; `parking_operations_total` pour les demandes (créées, rejouées, en conflit, représentées, acceptées, refusées) et les tentatives (acceptées, refusées). Séries à 0 dès le démarrage.
- Comptage métier derrière un port `OperationMetrics`, l'adaptateur Prometheus est branché dans `container.py` : le domaine ne dépend pas de `prometheus_client`.
- Dossier `monitoring/` : Dockerfile `prom/prometheus` (version fixée), `prometheus.yml` (Prometheus, payment local, payment sur Render, Booking, Access, Pricing), `compose.yaml` avec Grafana en bonus (source de données et tableau de bord provisionnés : état UP/DOWN, requêtes/s, erreurs, opérations métier), notice avec la simulation de panne et les requêtes PromQL.
- 5 tests ajoutés (168 avec base) ; vérifié sur un vrai serveur : un paiement `demo-refuse-once` fait monter refus, représentation puis acceptation.

### Problèmes

- Prometheus n'a pas pu être lancé depuis l'environnement de développement (pas d'accès à Docker) : configuration vérifiée syntaxiquement seulement, collecte réelle à constater au premier `docker compose up`.
- Hôtes Render de Booking, Access et Pricing inconnus : cibles laissées en `*-HOST` dans `prometheus.yml`.

### Suite

- Renseigner les hôtes des camarades dans `prometheus.yml`, vérifier qu'ils exposent `/metrics`, puis produire les trois graphiques et la démonstration de panne.
- Transmettre à Access les consignes de clé d'idempotence (`access:{stationnement_id}:exit`) et de `X-Correlation-ID`.
- Conserver le `correlation_id` en base pour qu'une transaction reprise après redémarrage garde le sien.
