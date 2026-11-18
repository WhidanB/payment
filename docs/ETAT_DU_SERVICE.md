# État du service `payment`

_Dernière mise à jour : 2026-09-03 — version `0.1.0` (MVP, passerelle simulée)_

Microservice du projet fil rouge « parking ». Il reçoit des demandes de paiement de
`booking` et `access`, ouvre des transactions pour les régler, et répond un statut
`PENDING` / `ACCEPTED` / `REFUSED`.

| | |
|---|---|
| **Repo** | https://github.com/WhidanB/payment (`master`) |
| **En ligne** | https://payment-xp8n.onrender.com |
| **Docs API** | https://payment-xp8n.onrender.com/docs (Swagger) · `/redoc` · `/openapi.json` |
| **Santé** | https://payment-xp8n.onrender.com/health |
| **Stack** | Python 3.12 · FastAPI · uvicorn · architecture hexagonale |
| **État** | ✅ déployé et vérifié en production · passerelle **simulée** (5 % de refus) · persistance **en mémoire** |

---

## 1. Périmètre métier

### Responsabilité

Gérer le **cycle de vie d'un paiement** à partir d'un montant **déjà calculé**, et garantir
qu'une même demande n'est **jamais encaissée deux fois** (idempotence). Le service **ne calcule
pas les prix**.

### Données possédées

- **Paiement / `PaymentRequest`** : `id` (UUID v7), `idempotency_key`, `amount` (centimes),
  `currency`, `reference` {type, id}, `source_service`, `status`, `created_at`, `updated_at`
- **Transaction / tentative** : `id` (UUID v7), `payment_id`, `attempt`, `status`,
  `created_at`, `resolved_at`
- L'**historique** des changements d'état (logs JSON)

### Données qu'il ne doit PAS posséder

- Le **prix** et la **logique de tarification** → `Pricing`
- La **grille tarifaire** et son versionnement
- L'**identité du véhicule** (plaque réelle, identifiant pseudonymisé)
- L'**état des places / le stock** → `Parking`
- Les **détails** de la réservation ou du stationnement (dates, type de place, durée) —
  seul `reference.id` est conservé
- Les **données bancaires réelles** du client → déléguées au PSP, jamais stockées en clair

### Objets métier

Paiement (agrégat) · Clé d'idempotence · Tentative de paiement · Résultat de passerelle.

### Actions principales

Ouvrir une demande (idempotente) · ouvrir une transaction · résoudre une transaction via la
passerelle · retenter automatiquement 1× après un refus · consulter l'état d'un paiement ·
exposer `/health` et `/docs`.
_Hors MVP : annuler, rembourser._

### Interactions

| Question | Réponse |
|---|---|
| Services qu'il appelle | **Aucun service interne.** Cible : le PSP externe (Stripe). |
| Services qui l'appellent | **Booking** (paiement à la commande d'une réservation) · **Access** (paiement à la sortie du stationnement) |
| Événements produits | **MVP : aucun** (résultat récupéré par polling). Cible : `PaymentAccepted` / `PaymentRefused` pour Booking, Access et Messages. |
| Événements consommés | **Aucun** — piloté par appels REST synchrones. |
| Workflow qui dépend de lui | **Confirmation d'une réservation** (Booking) et **autorisation de sortie** (Access) — bloquant dans les deux cas. |

### Problème technique particulier

L'**idempotence** couplée à la **gestion d'un cycle de vie asynchrone**. Un appel rejoué pour
la même opération métier ne doit pas produire deux encaissements, alors que l'état passe par un
`PENDING` asynchrone (15 s) et qu'un retry automatique suit un refus. Cas limite traité : deux
demandes concurrentes portant la même clé (sérialisées par un verrou par clé).

---

## 2. Modèle de données

```
PaymentRequest (agrégat)
├── id                UUID v7
├── idempotency_key   fournie par l'appelant, unique par opération métier
├── amount            entier, centimes, > 0
├── currency          "EUR"
├── reference         { type: BOOKING | PARKING_EXIT, id: string }
├── source_service    booking | access
├── status            PENDING | ACCEPTED | REFUSED   (dérivé des transactions)
├── max_attempts      2  (1 tentative initiale + 1 retry)
├── created_at / updated_at
└── transactions[]
        ├── id            UUID v7
        ├── payment_id
        ├── attempt       1, 2, …
        ├── status        PENDING | ACCEPTED | REFUSED
        └── created_at / resolved_at
```

Le cadrage prévoit à terme des statuts supplémentaires (`créé`, `annulé`, `remboursé`) ;
le MVP se limite aux trois issues demandées.

---

## 3. API

### `POST /payments` → `202 Accepted` (`200 OK` sur rejeu idempotent)

Requête :

```json
{
  "idempotency_key": "booking-4567-1",
  "amount": 1250,
  "currency": "EUR",
  "reference": { "type": "BOOKING", "id": "resa_01J9Z..." },
  "source_service": "booking"
}
```

| champ | règle |
|---|---|
| `idempotency_key` | requis, non vide |
| `amount` | entier, **centimes**, > 0 |
| `currency` | `EUR` |
| `reference.type` | `BOOKING` \| `PARKING_EXIT` |
| `reference.id` | id de la réservation ou du stationnement |
| `source_service` | `booking` \| `access` |

Réponse :

```json
{
  "payment_id": "01a06238-1840-79d3-b8c3-7c0183316c48",
  "status": "PENDING",
  "amount": 1250,
  "currency": "EUR",
  "reference": { "type": "BOOKING", "id": "resa_01J9Z..." },
  "source_service": "booking",
  "transactions": [
    { "transaction_id": "01a06238-1844-...", "attempt": 1, "status": "PENDING",
      "created_at": "2026-09-02T13:03:58.532Z", "resolved_at": null }
  ],
  "created_at": "2026-09-02T13:03:58.532Z",
  "updated_at": "2026-09-02T13:03:58.532Z"
}
```

- `422` — corps invalide (montant ≤ 0, `type`/`source_service` inconnu, clé manquante).
- Rejeu d'une `idempotency_key` déjà connue → `200` avec la demande existante, **sans**
  nouvelle transaction.

### `GET /payments/{payment_id}` → `200 OK`

Même schéma, tenu à jour (statut agrégé + toutes les transactions). `404` si inconnu.

### `GET /payments?limit=50` → `200 OK`

Liste des demandes récentes (plus récentes d'abord, `limit` entre 1 et 200), même schéma que
`GET /payments/{id}`. Protégée par `X-API-Key`. Sert à la console `/ui`.

### `GET /ui` (et `/`)

Console de démonstration et d'exploitation (page statique servie par le service, publique) :
liste et détail des demandes et transactions, création, rejeu idempotent, lot de 20 paiements,
journal des actions. `/` redirige vers `/ui`.

### `GET /health` → `200 OK`

```json
{ "status": "ok", "version": "0.1.0", "uptime_seconds": 408.798,
  "pending_delay_seconds": 15.0, "max_attempts": 2, "failure_rate": 0.05, "auth_enabled": false }
```

### Documentation

`/docs` (Swagger UI), `/redoc`, `/openapi.json` — fournis nativement par FastAPI.

### Authentification

Convention commune au projet : chaque route (sauf `/health`) exige l'en-tête
`X-API-Key` ; une clé par service appelant, transmise en privé (jamais dans Git).
Implémentée côté `payment` (`app/adapters/inbound/http/security.py`), visible dans
Swagger via le bouton *Authorize*. Si `PAYMENT_API_KEY` n'est pas configuré, la
vérification est désactivée (mode dev/test, et période de transition avant activation
coordonnée avec les appelants).

---

## 4. Comportement

### Idempotence

La `idempotency_key` identifie la demande. Un rejeu renvoie la demande existante
(`200`), sans créer de transaction ni rappeler la passerelle. Deux appels concurrents avec
la même clé sont sérialisés par un verrou par clé.

### Résolution asynchrone

1. `POST` → `202`, demande `PENDING` + transaction #1 `PENDING`.
2. Après **15 s** (`PAYMENT_PENDING_DELAY_SECONDS`), la passerelle est interrogée :
   95 % → `ACCEPTED`, 5 % → `REFUSED` (`PAYMENT_FAILURE_RATE`).
3. L'appelant récupère l'issue par **polling** `GET /payments/{id}`.

### Retry automatique (1×)

Sur `REFUSED`, si `attempt < max_attempts` (2) : une transaction #2 est créée, elle-même
`PENDING` 15 s. Si elle échoue aussi → demande `REFUSED`. Sinon → demande `ACCEPTED`.

```
POST ─▶ [tx1 PENDING] ──15s──▶ ACCEPTED ─▶ demande ACCEPTED
                          └──▶ REFUSED ─▶ [tx2 PENDING] ──15s──▶ ACCEPTED ─▶ demande ACCEPTED
                                                            └──▶ REFUSED ─▶ demande REFUSED
```

### Journalisation

Chaque changement d'état émet **une ligne JSON** sur `stdout` : `payment.requested`,
`transaction.created`, `gateway.authorize`, `transaction.accepted` / `transaction.refused`,
`payment.retry_scheduled`, `payment.accepted` / `payment.refused`, `payment.idempotent_hit`.
Champs : `payment_id`, `transaction_id`, `attempt`, `idempotency_key`, `amount`, `currency`,
`reference_*`, `source_service`, statut.

---

## 5. Architecture (hexagonale)

Le cœur métier (`app/domain`) n'importe **aucun** framework.

```
app/
├── domain/
│   ├── model/       enums · ids (UUID v7) · clock · errors · transaction · payment (agrégat + règles)
│   └── ports/       payment_repository · payment_gateway · resolution_scheduler
├── application/
│   ├── payment_service.py   request_payment · get_payment · _resolve_transaction (+ retry)
│   └── errors.py
├── adapters/
│   ├── inbound/http/   routes_payments · routes_health · schemas (DTO Pydantic)
│   └── outbound/       in_memory_payment_repository · simulated_payment_gateway · asyncio_resolution_scheduler
├── config.py         Settings (variables d'env, préfixe PAYMENT_)
├── container.py       composition root — point de câblage des adapters
├── logging_config.py  formatter JSON
└── main.py            create_app() + lifespan
```

**Points d'extension** (n'impactent que `container.py`) :

| Port | Adapter actuel | Adapter cible |
|---|---|---|
| `PaymentGateway` | `SimulatedPaymentGateway` | `StripePaymentGateway` |
| `PaymentRepository` | `InMemoryPaymentRepository` | adapter SQL / Postgres |
| `ResolutionScheduler` | `AsyncioResolutionScheduler` | worker persistant / file de tâches |

---

## 6. Configuration (variables d'environnement, préfixe `PAYMENT_`)

| Variable | Défaut | Effet |
|---|---|---|
| `PAYMENT_PENDING_DELAY_SECONDS` | `15` | durée du statut `PENDING` d'une transaction |
| `PAYMENT_FAILURE_RATE` | `0.05` | part de refus simulés par la passerelle |
| `PAYMENT_MAX_ATTEMPTS` | `2` | nombre de transactions par demande (1 + 1 retry) |

---

## 7. Tests

`pytest` — **14 tests**, < 1 s (passerelle forcée, résolution drainée manuellement, aucun sleep).

| Fichier | Couverture |
|---|---|
| `tests/test_idempotency.py` | même clé = même demande · pas de recharge après règlement · clés distinctes |
| `tests/test_payment_flow.py` | démarrage `PENDING` · résolution `PENDING → ACCEPTED` · format UUID v7 |
| `tests/test_retry.py` | refus → retry → accepté · deux refus → `REFUSED` · `max_attempts=1` = pas de retry |
| `tests/test_api.py` | e2e HTTP : health · 202 / 200 / 422 / 404 · polling |

Exploration manuelle : `scripts/requests.sh` (`BASE_URL=… ./scripts/requests.sh`).

---

## 8. Déploiement (Render)

- `render.yaml` : web service Python (plan free), `healthCheckPath: /health`,
  start `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1`
- `.python-version` : `3.12.8` (le défaut Render 3.14 empêchait l'installation de `pydantic-core`)
- Déploiement automatique à chaque push sur `master`

> **Un seul worker** : l'état est en mémoire et la résolution s'exécute comme tâche asyncio
> dans le process.

---

## 9. Limites connues / dette technique

| Limite | Conséquence | Levée par |
|---|---|---|
| Persistance **en mémoire** | tout est perdu au redeploy / à la mise en veille Render | adapter Postgres |
| Transaction `PENDING` non reprise après redémarrage | une transaction en attente au moment d'une coupure n'est jamais résolue | re-planification des `PENDING` au démarrage |
| **Un seul worker** obligatoire | pas de scalabilité horizontale | conséquence directe de la persistance mémoire |
| Passerelle **simulée** | aucun encaissement réel | adapter Stripe |
| Pas d'événements publiés | Booking/Access doivent **poller** | publication `PaymentResolved` sur un broker |
| Contrat d'API défini unilatéralement | risque de désalignement | validation avec les équipes Booking / Access |
| `render.yaml` : `PYTHON_VERSION` ignoré par Render | corrigé via `.python-version` | — |

---

## 10. Prochaines étapes (ordre conseillé)

1. **Valider le contrat d'API** avec les équipes `booking` et `access` (payload, génération de
   la clé d'idempotence).
2. **Persistance Postgres** (`PaymentRepository`) + **reprise des `PENDING`** au démarrage.
3. **Intégration Stripe** (`StripePaymentGateway`).
4. (Optionnel) **Publication d'événements** `PaymentAccepted` / `PaymentRefused` vers un broker
   pour Messages et pour éviter le polling.
