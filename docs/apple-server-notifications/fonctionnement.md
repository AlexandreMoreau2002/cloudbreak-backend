# Fonctionnement — notifications d'abonnement Apple

Apple envoie au backend un message signé après certains changements d'abonnement. Le backend vérifie d'abord que le message vient bien d'Apple et concerne l'application Cloudbreak en Sandbox. Il garde ensuite une trace de l'événement pour ne pas le traiter deux fois. Seuls les événements qui portent un changement de droit et une transaction Apple valide peuvent modifier l'abonnement du compte.

```text
Apple Sandbox
    |
    v
POST /api/v1/webhooks/apple
    |
    v
Vérifier le JWS extérieur (signature, bundle, environnement)
    |
    +-- TEST / préférence / échec de renouvellement / fin de grâce
    |      -> ledger d'idempotence -> 204, sans toucher subscriptions
    |
    +-- événement de droit avec signedTransactionInfo
           -> vérifier le JWS de la transaction (produit, compte, dates)
           -> ignorer doublon ou projection plus ancienne
           -> ledger + projection subscriptions dans la même transaction DB
           -> 204
```

Le `notificationUUID` du message est la clé du ledger `apple_subscription_events`. Pour les événements qui changent le droit, la lignée d'achat est liée à un seul compte Cloudbreak via `appAccountToken`. Une signature non valide ou une incohérence vérifiée provoque un rejet, sans accorder Premium. Un événement de droit dépourvu de transaction vérifiable est acquitté et consigné, sans projection.

La table `subscriptions` répond à la question « ce compte a-t-il actuellement accès à Premium ? » : elle contient notamment `plan`, `status` et `expires_at`. Le droit effectif exige un statut `trial` ou `active` et une expiration future. Un achat mensuel et un achat annuel y donnent tous deux `plan=premium` ; la cadence mensuelle/annuelle n'y est pas conservée. `DID_CHANGE_RENEWAL_PREF`, `DID_FAIL_TO_RENEW` et `GRACE_PERIOD_EXPIRED` sont volontairement consignés seulement dans le ledger et répondent 204, sans bascule immédiate du droit.

Les certificats racines Apple sous `app/resources/apple/` sont des ressources publiques de confiance livrées avec l'application, pas des secrets. Les clés privées Apple et les JWS valides ne sont pas des exemples à enregistrer dans Git.

## Fichiers concernés

| Fichier | Rôle |
| --- | --- |
| `app/api/v1/endpoints/subscription.py` | Route webhook publique et route de vérification du reçu pour le compte connecté. |
| `app/services/apple_store.py` et `app/resources/apple/` | Vérification cryptographique et certificats racines publics. |
| `app/services/subscription.py` | Propriété, idempotence, ordre des événements et projection du droit. |
| `app/models/apple_subscription_event.py` et `app/models/subscription.py` | Ledger et état courant. |
| `app/schemas/subscription.py` et `app/core/config.py` | Format des requêtes/réponses et paramètres Apple. |
| `tests/test_api_apple_webhook.py`, `tests/test_services_subscription.py`, `tests/test_services_apple_store.py` | Vérifications automatisées des branches principales. |
| `docs/apple-server-notifications.md`, `docs/apple-server-notifications/guide-test.md`, `http/apple-server-notifications.http`, `docs/security.md` | État des preuves, essai manuel, requête de diagnostic et décision sécurité. |

La configuration DEV et l'URL Sandbox sont constatées. La sélection V2 dans App Store Connect, le 204 d'un vrai test Apple et la projection d'une ligne après un événement de droit restent à vérifier ; voir [l'état des preuves](../apple-server-notifications.md).
