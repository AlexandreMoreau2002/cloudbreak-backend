# Story 4.3 — Premium StoreKit 2 (backend)

Le backend ne fait jamais confiance à un reçu décodé par le client. Il valide les JWS StoreKit 2 et les notifications V2 avec la bibliothèque serveur Apple, les certificats racines Apple inclus et les contraintes Cloudbreak : bundle ID, environnement et deux product IDs autorisés.

`POST /api/v1/user/subscription/verify` exige un compte permanent et compare l'`appAccountToken` Apple au UUID du JWT. La lignée `original_transaction_id` est attachée une seule fois : une seconde tentative depuis un autre compte répond 409. Les écritures gardent `plan = premium`; le statut et l'expiration déterminent le droit réel.

`POST /api/v1/webhooks/apple` est public parce qu'Apple l'appelle, mais son authentification est la signature JWS, pas un JWT client. Son ledger par `notificationUUID` empêche les effets doubles. Le quota garde aussi la compatibilité lecture avec les anciens plans `pro`, mais seulement pour un état `trial`/`active` non expiré.

Voir le [fonctionnement partagé](../../docs/story-4-3-storekit-2-abonnements/fonctionnement.md), le [guide de test](../../docs/story-4-3-storekit-2-abonnements/guide-test.md) et [`http/subscription.http`](../http/subscription.http).

