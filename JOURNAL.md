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
- 24 → 123 tests : matrice d'entrées invalides, valeurs limites, conflits d'idempotence, 25 appels concurrents, panne du prestataire, double résolution, invariants du domaine, adapters, contenu des logs. Couverture de branches 99,7 % (seuil 90 %).
- Les trois garde-fous critiques (verrou par clé, capture des exceptions de la passerelle, détection de conflit) vérifiés par mutation : les désactiver fait échouer les tests.
- Outillage : `ruff` (lint, format, complexité cyclomatique ≤ 10), `requirements-dev.txt` séparé du runtime, workflow GitHub Actions, `scripts/verify.sh` (mêmes contrôles en local).
- Documentation à jour : `docs/VERIFICATION.md` (nouvelle : commande unique, cas testés, catalogue des logs, scénarios manuels, vérification en production), README, `ETAT_DU_SERVICE.md`, guide d'intégration (409, bornes, `X-Request-ID`).
- Vérifié de bout en bout : démarrage avec les seules dépendances runtime, logs réels corrélés par `request_id`, console `/ui` toujours fonctionnelle dans Chromium headless.

### Problèmes

- Les tests de logs passaient à vide (aucune sortie capturée) : le handler gardait une référence à un ancien `stdout`. Corrigé en résolvant `sys.stdout` à chaque écriture, et ajout d'une assertion « sortie non vide ».
- `ruff` a signalé des commentaires `noqa` inutiles et des lignes trop longues : corrigés, un passage de format sur tout le dépôt.
- Branche « règle violée après validation du schéma » de la route non atteignable par HTTP : conservée comme filet de sécurité, couverte au niveau du domaine.

### Suite

- Pousser (7 commits en attente environ) et constater le premier passage de la CI GitHub Actions.
- Redéployer sur Render et vérifier `/ui`, `X-Request-ID` et le `409` en production.
- Optionnel : `pip-audit` en CI, branch protection sur `master`, tests automatisés de l'UI.
- Activer `PAYMENT_API_KEY` après avoir prévenu Booking et Access ; persistance Postgres et reprise des `PENDING`.
