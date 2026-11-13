# Story 4.3 — Premium StoreKit 2 (backend)

Le backend ne fait jamais confiance à un reçu décodé par le client. Il valide les JWS StoreKit 2 et les notifications V2 avec la bibliothèque serveur Apple, les certificats racines Apple inclus et les contraintes Cloudbreak : bundle ID, environnement et deux product IDs autorisés.

`POST /api/v1/user/subscription/verify` exige un compte permanent et compare l'`appAccountToken` Apple au UUID du JWT. La lignée `original_transaction_id` est attachée une seule fois : une seconde tentative depuis un autre compte répond 409. Les écritures gardent `plan = premium`; le statut et l'expiration déterminent le droit réel.

`POST /api/v1/webhooks/apple` est public parce qu'Apple l'appelle, mais son authentification est la signature JWS, pas un JWT client. Son ledger par `notificationUUID` empêche les effets doubles. Le quota garde aussi la compatibilité lecture avec les anciens plans `pro`, mais seulement pour un état `trial`/`active` non expiré.

Voir le [fonctionnement partagé](../../docs/story-4-3-storekit-2-abonnements/fonctionnement.md), le [guide de test](../../docs/story-4-3-storekit-2-abonnements/guide-test.md) et [`http/subscription.http`](../http/subscription.http).


## Règle d'entitlement (2026-10-06)

`plan` ne suffit jamais à savoir si quelqu'un est Premium : il reste `premium` après une expiration ou un
remboursement ; seuls `status` et `expires_at` changent. La règle unique est `app/domain/entitlement.py` :

> Premium **ssi** `plan ∈ {premium, pro}` ET `status ∈ {trial, active}` ET `expires_at` dans le futur.

Elle est utilisée par le quota (`check_quota`) et par `GET /api/v1/user/subscription` /
`POST /api/v1/user/subscription/verify` : le champ `plan` de la réponse vaut `premium` seulement si
l'entitlement est réellement actif, sinon `free` (le `status` reste celui stocké : `none`, `expired`,
`revoked`…). Avant ce correctif, l'API renvoyait `premium` même avec `status = none`, alors que le quota
n'était pas levé.

Comptes de test (`make seed-test`) : `pro@` et `test@` sont créés `plan = premium`, `status = active`,
expiration à +365 jours ; `freemium@` reste `free` / `none`.

Requête SQL du plan réel (jointure avec l'email copié depuis Supabase) :

```sql
SELECT u.email, s.plan, s.status, s.expires_at,
       (s.plan IN ('premium','pro') AND s.status IN ('trial','active') AND s.expires_at > now()) AS premium_actif
FROM subscriptions s LEFT JOIN users u ON u.supabase_user_id = s.user_id;
```
