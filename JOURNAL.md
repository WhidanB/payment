# Journal de bord — service `payment`

Suivi des avancées jour par jour, depuis le démarrage du projet. Les commits cités
sont ceux du repo (`git log`).

---

## 2026-09-02 — Cadrage, MVP complet et mise en ligne

**Cadrage.** Lecture du cadrage métier du projet fil rouge « parking » ; périmètre limité au
seul service `payment`. Décisions prises avec Dan :

- une **demande** de paiement (clé d'idempotence fournie par l'appelant) agrège 1..N
  **transactions** (tentatives, UUID v7) ;
- statuts `PENDING` / `ACCEPTED` / `REFUSED` ; `PENDING` dure 15 s (asynchrone) ;
- **retry automatique interne, une seule fois** après un refus ;
- résultat récupéré par **polling** `GET /payments/{id}` (pas de callback ni broker) ;
- stack **Python + FastAPI**, architecture **hexagonale**, persistance **en mémoire**
  derrière un port, passerelle **simulée** (5 % de refus) avant Stripe ;
- un commit par étape, déploiement sur **Render**.

**Réalisé (7 commits d'implémentation) :**

| Commit | Contenu |
|---|---|
| `2586814` | squelette FastAPI, config, logs JSON, `GET /health` |
| `75bc2f1` | domaine : agrégat `PaymentRequest`, `Transaction`, enums, ports |
| `190ccaa` | adapters : repo in-memory, gateway simulée, scheduler asyncio |
| `92fc728` | cas d'usage : idempotence, résolution asynchrone, retry unique |
| `2146260` | HTTP : `POST /payments` (202/200), `GET /payments/{id}`, Swagger `/docs` |
| `21ab4c9` | 14 tests (idempotence, flux nominal, refus → retry, e2e HTTP) |
| `86aa739` | `render.yaml` + contrat d'API dans le README |

**Mise en ligne.** Premier build Render en échec : Render a pris Python 3.14, sans wheel
`pydantic-core` précompilé (compilation Rust impossible, système en lecture seule). Corrigé
en épinglant Python via `.python-version` (`acaf0bc`, 3.12.8). Service déployé et vérifié en
production : health, cycle POST → polling → `ACCEPTED`, rejeu idempotent (200), 422, 404,
`/docs`, `/redoc`, `/openapi.json`.

**Autres.** URL live ajoutée au README (`e6c3bdb`), script d'exploration manuelle
`scripts/requests.sh` (`12418fa`). Environnement de dev sans `pip`/`venv` : pip amorcé via
`get-pip.py` dans un `.venv` ; pas de credentials git côté assistant, les push sont faits par Dan.

---

## 2026-09-03 — Documentation de l'état du service

- `docs/ETAT_DU_SERVICE.md` (`8e4d552`) : périmètre métier (les 12 questions du cadrage),
  modèle de données, contrat d'API, comportement, architecture, configuration, tests,
  déploiement, limites connues et prochaines étapes.
- Réponses aux 12 questions de cadrage du service (responsabilité, données possédées /
  interdites, appelants, événements, workflow dépendant, problème technique : idempotence +
  cycle de vie asynchrone).

---

## 2026-10-22 — Intégration avec Booking et Access, authentification

**Guide d'intégration** (`5c1f984`). `docs/INTEGRATION_BOOKING_ACCESS.md`, destiné aux équipes
Booking et Access : requêtes exactes pour les deux scénarios (réservation → `BOOKING`, sortie
→ `PARKING_EXIT`), statut → action (confirmer la réservation / ouvrir la barrière), recette de
polling (2 s, budget 40 s), convention de clé d'idempotence (`{service}:{id_métier}:{action}`),
tableau d'erreurs. Les deux exemples ont été validés en production (202).

**Authentification** (`8dea8a7`). Access a proposé une convention commune à tous les services :
en-tête `X-API-Key`, une clé par service, `/health` ouvert, clés échangées en privé, activation
coordonnée. Implémenté côté `payment` :

- dépendance FastAPI `APIKeyHeader` sur le routeur `/payments` (bouton *Authorize* dans Swagger) ;
- **inactive tant que `PAYMENT_API_KEY` n'est pas défini** → rien ne casse pour les appelants
  existants, activation décidée au moment voulu dans le dashboard Render ;
- `render.yaml` : variable déclarée avec `sync: false` (jamais dans Git) ;
- `scripts/requests.sh` : variable `API_KEY` optionnelle ;
- 5 nouveaux tests (19 au total) ; docs mises à jour.

**Échanges.**

- Clé générée pour `payment` et message prêt à envoyer à Booking et Access (même clé pour les
  deux : c'est la clé du service fournisseur) avec URL, lien du guide et exemple `curl`.
- Question de Dan sur `amount` en `int` : choix confirmé (centimes entiers, pas de `float` pour
  de l'argent — arithmétique exacte, même convention que Stripe).
- Rappel : le push déclenche le redéploiement Render ; le déploiement du code et l'activation de
  la clé sont deux étapes distinctes.
- README mis à jour (statut, authentification, configuration) et ce journal créé.

**En attente / à faire.**

- Activer `PAYMENT_API_KEY` sur Render, après avoir prévenu Booking et Access.
- Valider le contrat d'API avec Booking et Access (payload, génération de la clé d'idempotence).
- Persistance Postgres + reprise des transactions `PENDING` au démarrage.
- Adapter Stripe (`PaymentGateway`).
- Optionnel : événements `PaymentAccepted` / `PaymentRefused` pour éviter le polling.
