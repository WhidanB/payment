# Intégrer `payment` depuis `booking` et `access`

_Destiné aux équipes **Booking** et **Access**. Décrit comment appeler l'API `payment`,
interpréter ses réponses et agir en conséquence (valider une réservation / ouvrir la
barrière)._

- **Base URL (prod)** : `https://payment-xp8n.onrender.com`
- **Swagger interactif** : `https://payment-xp8n.onrender.com/docs`
- **Spec machine-readable** : `https://payment-xp8n.onrender.com/openapi.json`
  (importable directement dans Postman/Insomnia : *Import → Link*)
- Détail complet du service : [ETAT_DU_SERVICE.md](ETAT_DU_SERVICE.md)

> ⚠️ Render free tier : après ~15 min d'inactivité l'instance s'endort. Le premier appel
> qui la réveille peut prendre 30-50 s avant de répondre — prévoir une marge sur le
> premier appel si le service n'a pas été solicité récemment.

## 0. Authentification — `X-API-Key`

Convention commune à tous les services du projet : chaque route (sauf `/health`)
exige l'en-tête `X-API-Key`, avec une clé différente par service appelé.

```
X-API-Key: <clé que je vous ai transmise en privé>
```

- `401` si l'en-tête est absent ou faux.
- La clé vous est communiquée **en privé** (jamais sur le repo ni dans un canal
  partagé) ; stockez-la dans vos variables d'env (ex. `PAYMENT_API_KEY` côté Access,
  qui agrège une clé par service appelé).
- **Tant que je ne vous ai pas communiqué de clé, l'authentification est désactivée**
  (comportement actuel, rétro-compatible) — je vous préviens avant de l'activer, pour
  qu'on active l'en-tête des deux côtés en même temps sans rien casser.
- Les exemples ci-dessous incluent l'en-tête ; retirez-le tant que l'auth n'est pas
  activée.

---

## 1. Principe en une phrase

Vous **créez une demande de paiement** (`POST /payments`), vous **attendez** qu'elle
sorte de `PENDING` en **interrogeant régulièrement** `GET /payments/{id}` (polling — pas
de callback), puis vous agissez selon le statut final : `ACCEPTED` → vous continuez votre
workflow, `REFUSED` → vous le bloquez/annulez.

```
vous                          payment
 │  POST /payments  (montant déjà calculé)
 ├─────────────────────────────▶
 │  202 { status: PENDING, payment_id, transactions:[...] }
 ◀─────────────────────────────┤
 │
 │  GET /payments/{payment_id}   (répété, cf. §4)
 ├─────────────────────────────▶
 │  200 { status: PENDING | ACCEPTED | REFUSED, ... }
 ◀─────────────────────────────┤
 │
 │  (si REFUSED, payment a déjà retenté 1x en interne — status REFUSED est définitif)
```

**Délai jusqu'au statut final :** ~15 s, ou ~30 s si un retry interne a eu lieu (1 refus
suivi d'une 2ᵉ tentative). Prévoyez un budget de polling d'**au moins 35-40 s**.

---

## 2. Scénario Booking — paiement à la commande d'une réservation

Appelé **avant** de confirmer la réservation (cadrage §3.5, étape *Création* : Booking
obtient un prix de Pricing, demande le paiement, puis confirme si accepté).

**Requête :**

```bash
curl -X POST https://payment-xp8n.onrender.com/payments \
  -H 'content-type: application/json' \
  -H 'X-API-Key: <votre clé>' \
  -d '{
    "idempotency_key": "booking:resa_01J9Z3K2Q:create",
    "amount": 1250,
    "currency": "EUR",
    "reference": { "type": "BOOKING", "id": "resa_01J9Z3K2Q" },
    "source_service": "booking"
  }'
```

**Ce que vous faites du résultat (après polling, cf. §4) :**

| Statut final | Action côté Booking |
|---|---|
| `ACCEPTED` | Confirmer la réservation |
| `REFUSED` | Ne pas confirmer ; informer le client que le paiement a échoué (après le retry automatique, c'est définitif) |

---

## 3. Scénario Access — paiement à la sortie du stationnement

Appelé **après** que Pricing a calculé le montant du stationnement, **avant** d'autoriser
la sortie (cadrage §3.7, étape *Sortie* : paiement demandé → confirmé → sortie autorisée).

**Requête :**

```bash
curl -X POST https://payment-xp8n.onrender.com/payments \
  -H 'content-type: application/json' \
  -H 'X-API-Key: <votre clé>' \
  -d '{
    "idempotency_key": "access:stay_42:exit",
    "amount": 460,
    "currency": "EUR",
    "reference": { "type": "PARKING_EXIT", "id": "stay_42" },
    "source_service": "access"
  }'
```

**Ce que vous faites du résultat :**

| Statut final | Action côté Access |
|---|---|
| `ACCEPTED` | Autoriser la sortie (ouvrir la barrière) |
| `REFUSED` | Refuser la sortie ; le véhicule reste dans le parking jusqu'à résolution (hors périmètre MVP — cf. cadrage §5) |

---

## 4. Polling — comment attendre le résultat

Il n'y a **pas de callback/webhook** dans cette version : c'est vous qui interrogez
`GET /payments/{payment_id}` jusqu'à ce que `status` ne soit plus `PENDING`.

**Recette recommandée :** intervalle 2 s, timeout 40 s.

```text
payment_id ← réponse du POST
répéter jusqu'à 20 fois, toutes les 2s :
    body ← GET /payments/{payment_id}
    si body.status != "PENDING" :
        → traiter body.status (ACCEPTED / REFUSED) et sortir de la boucle
si on sort de la boucle sans résultat :
    → erreur applicative : traiter comme un paiement bloqué (à superviser),
      NE PAS considérer comme un refus
```

```bash
# exemple shell
for i in $(seq 1 20); do
  STATUS=$(curl -s -H "X-API-Key: $API_KEY" https://payment-xp8n.onrender.com/payments/$PAYMENT_ID | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
  [ "$STATUS" != "PENDING" ] && break
  sleep 2
done
echo "statut final: $STATUS"
```

Le champ `transactions[]` donne le détail des tentatives si besoin de diagnostic (attempt
1 `REFUSED`, attempt 2 `ACCEPTED`, etc.) — mais la décision métier se prend sur le
`status` **agrégé** de la demande, pas sur une transaction individuelle.

---

## 5. Idempotence — règle à respecter côté appelant

- Une `idempotency_key` = **une opération métier**. Réutilisez **la même clé** si vous
  rejouez le même appel (timeout réseau, retry applicatif, re-déploiement) — `payment`
  vous renverra la demande existante (`200`) sans créer de 2ᵉ transaction ni double
  encaissement.
- Convention recommandée : `{service}:{votre_id_metier}:{action}`
  - Booking : `booking:{reservation_id}:create`
  - Access : `access:{stationnement_id}:exit`
- Ne générez **jamais** une nouvelle clé pour "réessayer" un paiement déjà en `PENDING`
  ou `REFUSED` définitif — si le client doit retenter un paiement différent, c'est une
  **nouvelle** opération métier (nouvelle clé).

---

## 6. Gestion des erreurs

| Code | Cas | Action recommandée |
|---|---|---|
| `202` | demande créée | démarrer le polling |
| `200` | rejeu d'une `idempotency_key` connue | traiter comme une réponse normale (idempotent, pas une erreur) |
| `401` | `X-API-Key` absent ou incorrect | vérifier la clé configurée côté appelant — **bug de config**, pas de retry utile |
| `422` | corps invalide (montant ≤ 0, `reference.type`/`source_service` inconnu, clé manquante) | **bug côté appelant** — corriger l'appel, ne pas retenter tel quel |
| `404` | `GET /payments/{id}` sur un id inconnu | ne devrait pas arriver si vous utilisez l'id renvoyé par le `POST` — à investiguer |
| `5xx` / timeout réseau / pas de réponse | panne ou cold start Render | **retry avec la même `idempotency_key`** après un court délai — sans risque de double paiement |

---

## 7. Ce qui n'existe pas encore (à anticiper)

- **Pas d'événements asynchrones** (`PaymentAccepted`/`PaymentRefused` sur un broker) :
  le polling est la seule méthode pour l'instant.
- **Persistance en mémoire** côté `payment` : un redeploy/mise en veille Render efface
  l'historique des demandes en cours. Sans impact sur une demande déjà résolue consultée
  juste après, mais ne construisez pas de logique qui dépend de paiements anciens
  retrouvables indéfiniment.
- `amount` est un **entier en centimes** (`1250` = 12,50 €), `currency` figé à `"EUR"`.

---

## 8. Contact

Service détenu par Dan (`payment`). Pour toute évolution de contrat (nouveau champ,
nouveau `reference.type`, etc.), ouvrir une discussion avant d'intégrer côté
Booking/Access — le contrat ci-dessus est versionné dans ce repo.
