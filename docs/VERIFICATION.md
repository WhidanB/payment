# Vérifier et reproduire le fonctionnement du service

Ce document explique comment contrôler que `payment` se comporte comme décrit, sur sa machine
ou en production, et où se trouve chaque garantie (règle, test, log).

## 1. Tout vérifier en une commande

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./scripts/verify.sh
```

`verify.sh` enchaîne exactement ce que fait la CI (`.github/workflows/ci.yml`) :

| Étape | Outil | Seuil |
|---|---|---|
| Lint (erreurs, imports, bugs probables, simplifications, complexité cyclomatique) | `ruff check` | aucune erreur, complexité ≤ 10 par fonction |
| Format | `ruff format --check` | aucun écart |
| Tests + couverture de branches | `pytest --cov` | tous verts, couverture ≥ 90 % (actuellement ~99,7 %) |

Résultat attendu (à la date du 18 novembre) : `163 passed` (ou `148 passed, 15 skipped` sans base de test), `Total coverage: 99.xx%`.

Les tests sont déterministes : pas de `sleep`, passerelle forcée, planificateur piloté à la main
(`tests/conftest.py`). Un échec est donc un vrai défaut, pas un test instable.

## 2. Où est testé quoi

### Entrées invalides (`tests/test_validation.py`)

| Cas | Résultat attendu |
|---|---|
| `amount` = 0, négatif, décimal (`12.5`), texte (`"1250"`), booléen, null, absent | `422`, rien n'est créé |
| `amount` > 10 000 000 centimes | `422` |
| `currency` ≠ `EUR` (`USD`, `eur`) | `422` |
| `idempotency_key` vide, blanche, > 200 caractères, absente | `422` |
| `reference.id` vide, blanc, > 100 caractères ; `reference` absente | `422` |
| `reference.type` ou `source_service` inconnus | `422` |
| Corps non JSON, tableau, `null`, vide, formulaire | `422` |
| Champs supplémentaires inconnus | ignorés (`202`) |
| `PUT /payments`, `DELETE /payments/x`, `POST /health` | `405` |
| `GET /payments/<id inconnu>` (y compris 500 caractères) | `404` |
| `GET /payments?limit=` hors de 1..200 ou non numérique | `422` |

### Cas limites métier

| Cas | Test | Comportement garanti |
|---|---|---|
| 1 centime, montant maximal, clé de 200 caractères, id de 100 caractères, Unicode | `test_boundary_values_are_accepted` | acceptés (`202`) |
| Espaces autour de la clé | `test_whitespace_around_key_…` | clé normalisée, le rejeu est reconnu |
| Rejeu identique | `test_idempotency.py` | `200`, même `payment_id`, aucune nouvelle transaction, aucun nouvel appel à la passerelle |
| Même clé, montant / référence / appelant différents | `test_same_key_with_a_different_payload_…` | **`409`**, la demande d'origine est inchangée |
| 25 appels simultanés avec la même clé | `test_concurrent_requests_…` | une seule demande créée, **un seul encaissement** |
| Clés différentes en parallèle | `test_concurrent_requests_with_different_keys_…` | demandes indépendantes |
| Refus puis retry | `test_retry.py` | 2ᵉ transaction automatique, une seule |
| Deux refus | `test_two_refusals_…` | demande `REFUSED`, exactement 2 appels à la passerelle |
| La passerelle lève une exception (panne du prestataire) | `test_gateway_exception_…`, `test_persistent_gateway_outage_…` | traitée comme un refus (retry applicable), **jamais de transaction bloquée en `PENDING`** |
| Résolution déclenchée deux fois / tardive | `test_resolving_the_same_transaction_twice_…` | une seule passerelle appelée, demande réglée inchangée |
| Paiement disparu au moment de la résolution | `test_resolution_of_a_vanished_payment_…` | sans effet, sans erreur |
| Refus simulés ≈ 5 % | `test_default_rate_refuses_about_five_percent` | 4 à 6 % sur 20 000 tirages (graine fixe) |
| Référence `demo-refuse-once…` | `test_demo_scenarios_show_the_refusal_…`, `test_demo_reference_ids_…` | tentative 1 `REFUSED`, retry `ACCEPTED`, demande `ACCEPTED` |
| Référence `demo-refuse-always…` | idem | tentatives 1 et 2 `REFUSED`, demande `REFUSED` |
| Clé API absente / fausse / correcte, `/health` et `/ui` ouverts | `test_api_key.py` | `401` / `401` / OK |

### Règles du domaine (`tests/test_domain.py`)

Invariants de création, UUID v7 (demande et transactions, uniques et ordonnés dans le temps),
numérotation des tentatives et borne `max_attempts`, une transaction ne se résout qu'une fois,
comparaison métier utilisée pour détecter un conflit d'idempotence.

### Persistance (`tests/test_repository_contract.py`, `tests/test_persistence.py`)

| Cas | Comportement garanti |
|---|---|
| Même contrat pour le stockage en mémoire et PostgreSQL | aller-retour complet, mise à jour, identifiant inconnu ou malformé → `None`, tri, copies indépendantes |
| Deux demandes avec la même clé | refusé par la base (`IdempotencyKeyTaken`), une seule ligne |
| Deux instances qui reçoivent la même clé au même instant | une seule demande créée, l'autre répond comme un rejeu (`200`) ou un conflit (`409`) |
| Redémarrage du service | les paiements sont toujours là, le rejeu d'une clé est toujours reconnu |
| Service arrêté pendant un `PENDING` | au démarrage, la transaction est replanifiée pour le temps restant puis résolue |
| Base injoignable | `/health?deep=true` → `status: degraded`, `database: unreachable` ; `/health` simple ne touche jamais la base |
| Chaîne de connexion copiée depuis Neon | acceptée telle quelle (`channel_binding`, propre à libpq, est retiré) |

Lancer avec une base jetable :

```bash
PAYMENT_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres ./scripts/verify.sh
```

### Adapters (`tests/test_adapters.py`)

Passerelle simulée (taux 0, 1, 5 %, taux invalide), dépôt en mémoire (copies isolées, recherche
par clé, tri et limite), planificateur asyncio (exécution différée, callback défaillant journalisé
sans arrêter les autres, arrêt propre).

## 3. Logs exploitables (`tests/test_logging.py`)

Chaque ligne de log est un objet JSON : `timestamp`, `level`, `logger`, `message`, plus les
champs de l'événement. Un seul format, filtrable avec `jq`.

| Événement (`message`) | Quand | Champs utiles |
|---|---|---|
| `http.request` | chaque appel HTTP | `method`, `path`, `status`, `duration_ms` |
| `payment.requested` | nouvelle demande | `payment_id`, `idempotency_key`, `amount`, `reference_*`, `source_service` |
| `transaction.created` | ouverture d'une tentative | `transaction_id`, `attempt` |
| `gateway.authorize` | appel à la passerelle | `approved`, `scenario` (`random`, `refuse_once`, `refuse_always`), `attempt`, `transaction_id`, `detail` |
| `transaction.accepted` / `transaction.refused` | résolution d'une tentative | `attempt`, `detail` |
| `payment.retry_scheduled` | retry automatique | `attempt` |
| `payment.accepted` / `payment.refused` | statut final de la demande | `attempts` |
| `payment.idempotent_hit` | rejeu reconnu | |
| `payment.idempotency_conflict` (WARNING) | même clé, requête différente | |
| `gateway.error` (ERROR) | exception du prestataire | `exception` |
| `http.unhandled_error` (ERROR) | exception non prévue (réponse `500` JSON) | `exception`, `correlation_id` |

**Corrélation.** Chaque requête reçoit un `correlation_id` : l'en-tête `X-Correlation-ID` de l'appelant
s'il est valide (`[A-Za-z0-9._-]`, 64 caractères max), sinon un UUID v7 généré. Il est renvoyé dans
l'en-tête de la réponse et porté par **toutes** les lignes liées, y compris la résolution
asynchrone 15 s plus tard. Pour reconstituer l'histoire d'un paiement :

```bash
jq -c 'select(.correlation_id == "demo-trace-1")' logs.jsonl
jq -c 'select(.payment_id == "<payment_id>") | {timestamp, message, attempt, transaction_status}' logs.jsonl
```

Bruit : `/health` et `GET /payments` (sondés par Render et la console) ne sont journalisés qu'au niveau
`DEBUG`. `PAYMENT_LOG_LEVEL=DEBUG` les affiche. La clé API n'apparaît jamais dans les logs (testé).

## 4. Reproduire un scénario à la main

| Je veux voir… | Commande |
|---|---|
| Le flux nominal, le rejeu, le polling, 422/404, un lot de 30 | `BASE_URL=http://localhost:8000 ./scripts/requests.sh` |
| Un refus puis son retry accepté, à coup sûr | créer un paiement avec `"reference": {"type": "BOOKING", "id": "demo-refuse-once-1"}` (ou bouton « Refus puis retry accepté » dans `/ui`) : `REFUSED → ACCEPTED` |
| Un refus définitif, à coup sûr | référence `demo-refuse-always-1` (ou bouton « Refus définitif ») : `REFUSED → REFUSED`, demande `REFUSED` ; fonctionne aussi en production |
| Tous les paiements refusés | `PAYMENT_FAILURE_RATE=1 PAYMENT_PENDING_DELAY_SECONDS=3 uvicorn app.main:create_app --factory` |
| La nouvelle présentation par l'appelant après un refus définitif | rejouer la même clé : `200`, toujours `REFUSED` ; créer une nouvelle demande (nouvelle clé) : nouvel essai (bouton « Représenter ce paiement » dans `/ui`) |
| Un paiement toujours accepté | `PAYMENT_FAILURE_RATE=0` |
| Un conflit d'idempotence | envoyer deux `POST` avec la même `idempotency_key` et des montants différents : `409` |
| La corrélation des logs | envoyer `-H 'X-Correlation-ID: demo-1'` puis `grep demo-1` dans la sortie du serveur |
| Tout depuis un navigateur | ouvrir `/ui` (création, rejeu, lot de 20, journal des actions) |

## 5. Vérifier la production

```bash
URL=https://payment-xp8n.onrender.com
curl -s $URL/health                     # version, délai PENDING, taux de refus, auth active ou non
./scripts/requests.sh                   # BASE_URL=$URL, API_KEY=... si la clé est activée
```

La console `/ui` montre le même état en direct. Les logs se lisent dans l'onglet **Logs** du service
Render (un JSON par ligne).

## 6. Limites connues de la vérification

- Les tests PostgreSQL ne tournent que si `PAYMENT_TEST_DATABASE_URL` est défini (toujours en CI, avec
  un Postgres 16 ; en local ils sont sinon ignorés). La base Neon de production n'est jamais utilisée
  par les tests.
- Plusieurs instances simultanées ne sont pas couvertes au-delà de la création (la résolution différée
  reste dans le process : un seul worker).
- La branche « règle métier violée après validation du schéma » de la route `POST /payments`
  n'est pas atteignable par HTTP (le schéma refuse déjà ces cas) ; elle reste comme filet de sécurité
  et est couverte au niveau du domaine (`test_domain.py`).
- L'interface `/ui` est vérifiée manuellement dans un navigateur (Chromium headless), pas dans la CI.
- La CI GitHub Actions est configurée mais son premier passage reste à constater après le push.
