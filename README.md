# Payment

## Rôle du service

Gérer le cycle de vie d'un paiement à partir d'un montant déjà calculé, et garantir qu'une même demande n'est jamais encaissée deux fois.

Payment ne calcule pas les prix : il reçoit un montant et une référence de ce qui est payé (réservation ou stationnement), ouvre une ou plusieurs transactions pour le régler et renvoie un statut `PENDING` / `ACCEPTED` / `REFUSED`. La passerelle de paiement est **simulée** (95 % d'acceptation, 5 % de refus) en attendant Stripe.

## Version actuelle

0.1.0 (MVP, passerelle simulée)

## URLs

| Ressource | URL |
|---|---|
| Service déployé | https://payment-xp8n.onrender.com |
| Console de démonstration (UI) | https://payment-xp8n.onrender.com/ui |
| Swagger UI | https://payment-xp8n.onrender.com/docs |
| ReDoc | https://payment-xp8n.onrender.com/redoc |
| OpenAPI JSON | https://payment-xp8n.onrender.com/openapi.json |
| Health check | https://payment-xp8n.onrender.com/health |

Render gratuit : après ~15 min d'inactivité, le premier appel met 30 à 50 s à répondre (réveil de l'instance).

## Dépôt

| Dépôt | URL |
|---|---|
| Backend | https://github.com/WhidanB/payment |

## Documentation

| Document | Contenu |
|---|---|
| [docs/INTEGRATION_BOOKING_ACCESS.md](docs/INTEGRATION_BOOKING_ACCESS.md) | Guide pour Booking et Access : exemples par scénario, polling, idempotence, erreurs |
| [docs/ETAT_DU_SERVICE.md](docs/ETAT_DU_SERVICE.md) | État détaillé du service : périmètre, modèle, comportement, limites |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | Vérifier et reproduire le fonctionnement : commande unique, cas testés, logs, scénarios manuels |
| [JOURNAL.md](JOURNAL.md) | Journal de travail jour par jour |

## Dépendances avec les autres services

Payment est un service **passif**. Il ne fait aucun appel sortant.

| Service | Direction | Description |
|---|---|---|
| Booking | Booking appelle Payment | Paiement anticipé à la commande d'une réservation (`reference.type = BOOKING`). Booking confirme la réservation une fois le paiement `ACCEPTED` |
| Access | Access appelle Payment | Paiement du stationnement à la sortie (`reference.type = PARKING_EXIT`). Access ouvre la barrière une fois le paiement `ACCEPTED` |

Aucun flux asynchrone (broker) n'est utilisé pour l'instant : le résultat est récupéré par **polling** de `GET /payments/{id}`, le paiement étant asynchrone par nature (`PENDING` pendant 15 s).

## Comportement

- Une **demande de paiement** est identifiée par une clé d'idempotence fournie par l'appelant. Rejouer la même clé renvoie la demande existante (`200`), sans nouvelle transaction ni nouvel encaissement.
- Une demande regroupe **1 à N transactions** (tentatives), chacune unique (UUID v7).
- Une transaction reste `PENDING` pendant **15 s**, puis passe à `ACCEPTED` ou `REFUSED`.
- Après un refus, le service ouvre automatiquement **une seule** transaction de retry (de nouveau `PENDING` 15 s). Si elle échoue aussi, la demande est `REFUSED`.
- Le statut final est donc disponible au bout de ~15 s, ou ~30 s en cas de retry.
- Chaque changement d'état est journalisé en une ligne JSON.

## Interface de démonstration

La console `/ui` (servie par le service lui-même, `/` y redirige) permet de manipuler et d'observer le service sans outil externe :

- **Objets et états** : liste des demandes de paiement (statut, montant, référence, appelant, nombre de tentatives, progression du délai `PENDING`), compteurs par statut, détail d'une demande avec chacune de ses transactions (identifiant, tentative, statut, durée) et la réponse JSON brute.
- **Opérations** : créer une demande (clé d'idempotence, montant en centimes, référence, service appelant), **rejouer la même requête** pour montrer l'idempotence (`200`, même `payment_id`, pas de nouvelle transaction), générer un lot de 20 paiements pour voir la répartition réelle.
- **Refus et nouvelle présentation, à coup sûr** : « Refus puis retry accepté » et « Refus définitif » créent une demande dont l'issue est garantie. La colonne Tentatives montre la chaîne (`REFUSED → PENDING`, puis `REFUSED → ACCEPTED` ou `REFUSED → REFUSED`), le détail raconte ce qui s'est passé et relie les tentatives. Une demande définitivement refusée peut être **représentée** (nouvelle demande, nouvelle clé, même montant et même référence).
- **Résultat des actions** : journal des appels effectués depuis la page (code HTTP, résumé, requête et réponse dépliables) et rafraîchissement automatique toutes les 2 s.
- **Contexte** : version, délai `PENDING`, nombre max de tentatives, taux de refus simulé, authentification active ou non, et rappel du vocabulaire métier.
- La page est publique ; si l'authentification est active, saisir la clé API en haut à droite (gardée uniquement pour l'onglet, dans `sessionStorage`).

## Tester le service

### Health check

```bash
curl https://payment-xp8n.onrender.com/health
```

### Créer une demande de paiement (réservation)

```bash
curl -X POST https://payment-xp8n.onrender.com/payments \
     -H "Content-Type: application/json" \
     -H "X-API-Key: <clé>" \
     -d '{"idempotency_key":"booking:resa_1:create","amount":1250,"currency":"EUR","reference":{"type":"BOOKING","id":"resa_1"},"source_service":"booking"}'
```

Réponse `202` avec le `payment_id` et le statut `PENDING`.

### Créer une demande de paiement (sortie de parking)

```bash
curl -X POST https://payment-xp8n.onrender.com/payments \
     -H "Content-Type: application/json" \
     -H "X-API-Key: <clé>" \
     -d '{"idempotency_key":"access:stay_42:exit","amount":460,"currency":"EUR","reference":{"type":"PARKING_EXIT","id":"stay_42"},"source_service":"access"}'
```

### Consulter le résultat (polling)

```bash
curl https://payment-xp8n.onrender.com/payments/<payment_id> -H "X-API-Key: <clé>"
```

À répéter (toutes les 2 s) jusqu'à ce que `status` ne soit plus `PENDING`.

L'en-tête `X-API-Key` n'est exigé qu'une fois la clé activée sur le serveur (voir Sécurité). Le script `scripts/requests.sh` enchaîne tous ces scénarios (création, rejeu idempotent, polling, erreurs 422/404, recherche d'un refus) : `BASE_URL=... API_KEY=... ./scripts/requests.sh`.

## Contrat d'API

| Route | Description | Codes |
|---|---|---|
| `POST /payments` | Crée une demande et sa première transaction | `202` (créée), `200` (rejeu idempotent), `401`, `409` (clé déjà utilisée avec une requête différente), `422` |
| `GET /payments/{payment_id}` | Statut agrégé et toutes les transactions | `200`, `401`, `404` |
| `GET /payments?limit=50` | Demandes récentes, les plus récentes d'abord (utilisé par l'UI, 1 à 200) | `200`, `401`, `422` |
| `GET /health` | Santé du service, avec la configuration utile à l'UI | `200` |
| `GET /ui` | Console de démonstration | `200` |

Corps de `POST /payments` :

| Champ | Règle |
|---|---|
| `idempotency_key` | Obligatoire, unique par opération métier, 1 à 200 caractères (espaces de bord retirés) |
| `amount` | **Entier** en centimes, de 1 à 10 000 000 (`1250` = 12,50 €). `"1250"`, `12.5` et `true` sont refusés |
| `currency` | `EUR` |
| `reference.type` | `BOOKING` ou `PARKING_EXIT` |
| `reference.id` | Identifiant de la réservation ou du stationnement, 1 à 100 caractères |
| `source_service` | `booking` ou `access` |

Toute entrée invalide renvoie `422` avec le champ fautif dans `detail`, sans rien créer. Rejouer une clé avec la **même** requête renvoie `200` ; la rejouer avec une requête **différente** (montant, référence ou appelant) renvoie `409` et ne modifie pas la demande d'origine. Chaque réponse porte un en-tête `X-Request-ID` (celui envoyé par l'appelant s'il est valide, sinon généré) retrouvable dans les logs.

Le détail des scénarios, du polling et de la gestion d'erreurs est dans le [guide d'intégration](docs/INTEGRATION_BOOKING_ACCESS.md).

## Sécurité

| Action | Protection |
|---|---|
| `POST /payments`, `GET /payments/{id}` | En-tête `X-API-Key` (401 si absent ou faux) |
| `GET /payments` (liste) | En-tête `X-API-Key` |
| `/health`, `/ui`, `/docs`, `/redoc`, `/openapi.json` | Publics |

| Mesure | Détail |
|---|---|
| Convention | Commune à tous les services : `X-API-Key`, une clé par service, `/health` ouvert, clés échangées en privé |
| Clé | Variable d'environnement `PAYMENT_API_KEY`, jamais dans le code ni dans Git (`sync: false` dans `render.yaml`) |
| Activation | Le contrôle n'est actif que si `PAYMENT_API_KEY` est défini sur le serveur, pour ne casser aucun appelant avant une bascule coordonnée |
| Swagger | Schéma de sécurité déclaré, bouton **Authorize** pour tester avec la clé |
| Validation des entrées | Pydantic v2 (montant > 0, types et énumérations contrôlés) |
| Idempotence | Aucun double encaissement en cas de rejeu ; verrou par clé pour les appels concurrents |

## Fonctionnalités

- [x] Je peux créer une demande de paiement et obtenir immédiatement un statut `PENDING`.
- [x] Je peux consulter le statut d'une demande et toutes ses transactions.
- [x] Une même demande rejouée avec la même clé n'est jamais encaissée deux fois.
- [x] Chaque transaction a un identifiant unique (UUID v7).
- [x] Le paiement est asynchrone : `PENDING` pendant 15 s puis `ACCEPTED` ou `REFUSED`.
- [x] Un refus déclenche un retry automatique (une seule fois).
- [x] Environ 5 % des paiements simulés sont refusés, pour tester le comportement en cas d'échec.
- [x] Un refus suivi de sa nouvelle présentation automatique se démontre à coup sûr (références `demo-refuse-once…` / `demo-refuse-always…`, boutons dans `/ui`).
- [x] Chaque transaction et chaque changement d'état est journalisé (JSON, corrélé par `request_id`).
- [x] Les entrées invalides sont refusées (`422`) et la réutilisation d'une clé avec une requête différente est refusée (`409`).
- [x] Une panne de la passerelle ne laisse jamais une transaction bloquée en `PENDING`.
- [x] Le comportement est vérifiable en une commande (`./scripts/verify.sh`) et par la CI.
- [x] Le service expose un endpoint `/health`.
- [x] La documentation Swagger/ReDoc est générée automatiquement.
- [x] Une interface web (`/ui`) permet de créer, rejouer, observer les demandes et leurs transactions.
- [x] Je peux lister les demandes récentes (`GET /payments`).
- [x] Les routes de paiement sont protégées par `X-API-Key` (activation côté serveur à coordonner).
- [x] Le service est déployé sur Render.
- [ ] Activation de la clé API en production.
- [ ] Communication réelle avec Booking.
- [ ] Communication réelle avec Access.
- [ ] Persistance durable (Postgres) et reprise des transactions `PENDING` après redémarrage.
- [ ] Intégration de Stripe.

## Architecture

Architecture hexagonale : le cœur métier n'importe aucun framework.

```
app/domain/model/       entités et règles (PaymentRequest, Transaction, enums, UUID v7)
app/domain/ports/       interfaces (PaymentRepository, PaymentGateway, ResolutionScheduler)
app/application/        cas d'usage (PaymentService)
app/adapters/inbound/   routes FastAPI, DTO, sécurité X-API-Key
app/adapters/outbound/  repo en mémoire, passerelle simulée, scheduler asyncio
app/container.py        composition root : point de câblage des adapters
app/main.py             fabrique de l'application
```

Pour brancher Stripe : ajouter `stripe_payment_gateway.py` implémentant `PaymentGateway` et le câbler dans `container.py`. Le domaine ne change pas. Même principe pour un repository Postgres.

## Stack technique

- Python 3.12 (Render, `.python-version`), FastAPI, Pydantic v2, pydantic-settings, uuid-utils, uvicorn
- Architecture hexagonale (domain / application / adapters)
- Tests : pytest + httpx, 131 tests (domaine, adapters, flux asynchrone, validation, cas limites, logs, API), couverture de branches ~99,7 % (seuil 90 %) ; UI vérifiée dans Chromium headless (Playwright, hors dépendances du projet)
- Qualité : ruff (lint, format, complexité cyclomatique ≤ 10), GitHub Actions (`.github/workflows/ci.yml`), `scripts/verify.sh` pour les mêmes contrôles en local
- Interface : une page HTML/CSS/JS vanilla sans dépendance, servie par FastAPI
- Logs JSON structurés, `X-Request-ID` de bout en bout (y compris la résolution asynchrone)
- Déploiement : Render (`render.yaml`, un seul worker, déploiement automatique à chaque push sur `master`)

## Lancer en local

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt = runtime seul (ce que Render installe)
uvicorn app.main:create_app --factory --reload
./scripts/verify.sh                   # ruff + format + pytest + couverture (comme la CI)
```

Swagger : http://127.0.0.1:8000/docs

Pour voir un refus suivi du retry, sans changer la configuration : utiliser une référence commençant par `demo-refuse-once` (refusée à la tentative 1, acceptée au retry) ou `demo-refuse-always` (refusée aux deux tentatives), ou les boutons de démonstration de `/ui`. Pour que tous les paiements soient refusés : `PAYMENT_FAILURE_RATE=1 PAYMENT_PENDING_DELAY_SECONDS=3 uvicorn app.main:create_app --factory`.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `PAYMENT_PENDING_DELAY_SECONDS` | `15` | Durée du statut `PENDING` d'une transaction |
| `PAYMENT_FAILURE_RATE` | `0.05` | Part de refus simulés par la passerelle |
| `PAYMENT_MAX_ATTEMPTS` | `2` | Transactions par demande (1 initiale + 1 retry) |
| `PAYMENT_LOG_LEVEL` | `INFO` | Niveau de logs ; `DEBUG` journalise aussi `/health` et la liste sondée par l'UI |
| `PAYMENT_API_KEY` | non défini | Clé attendue dans `X-API-Key` ; non défini = contrôle désactivé |

## Limites connues

- Persistance en mémoire : l'historique est perdu à chaque redéploiement ou mise en veille de Render.
- Une transaction `PENDING` au moment d'un redémarrage n'est jamais résolue.
- Un seul worker obligatoire (état et tâches de résolution dans le process).
- Passerelle simulée : aucun encaissement réel. Les références commençant par `demo-refuse-` déclenchent des refus de démonstration ; elles n'auront plus d'effet avec Stripe.
- Pas d'événements publiés : les appelants doivent faire du polling.

## Aspects de maturité

| Aspect | État | Commentaire |
|---|---|---|
| Métier | 3 - Maîtrisé | Responsabilité, objets et règles clairs : idempotence, cycle de vie asynchrone, retry unique |
| API / Déploiement | 3 - Maîtrisé | En ligne sur Render, /health, Swagger/ReDoc, version 0.1.0 |
| Intégration | 1 - Défini | Contrat d'API et guide fournis à Booking et Access, pas encore d'appel réel validé. Passera à 2 avec un premier appel réel de leur part |
| Interface | 2 - Fonctionnel | Console `/ui` : objets, états, opérations, journal des actions, clé API. Pas de tests automatisés de l'UI dans le dépôt |
| Qualité | 3 - Maîtrisé | 131 tests dont entrées invalides, cas limites, concurrence et panne du prestataire (vérifiés par mutation), couverture ~99,7 %, ruff + complexité, logs JSON corrélés, [guide de vérification](docs/VERIFICATION.md). Pas d'audit des dépendances (pip-audit) |
| CI/CD | 2 - Fonctionnel | Déploiement continu Render sur push et workflow GitHub Actions (lint, format, tests, couverture) ; premier passage à constater après le push, pas de branch protection |
| Sécurité | 2 - Fonctionnel | `X-API-Key` implémentée, pas encore activée en production. Pas de rate limiting ni de headers de sécurité |
