# Guide de test manuel — Apple Sandbox

Ce guide prépare la validation sur appareil réel. Au 2026-10-06, l'URL Sandbox est sauvegardée et le backend DEV était disponible, mais aucune notification de test reçue, aucun 204 de callback Apple et aucune projection de ligne après rejeu n'ont été observés. Ne cocher un résultat que lorsque sa preuve est réellement recueillie.

## Prérequis

1. Disposer d'un iPhone réel avec la version DEV de Cloudbreak, d'un compte testeur Sandbox App Store et d'un compte Cloudbreak permanent connecté. Les achats, renouvellements et restaurations sur l'appareil sont des **étapes humaines sur iPhone** ; l'agent ne peut pas les exécuter.
2. Vérifier dans App Store Connect l'URL Sandbox `https://dev-api.cloudbreak-app.com/api/v1/webhooks/apple`, la configuration App Store Server Notifications **Version 2 si un sélecteur est accessible**, et l'absence de modification involontaire de Production. Le contrôle du 2026-10-06 n'a pas pu prouver la sélection V2.
3. Vérifier la santé DEV (`GET /health`), `ENVIRONMENT=development`, `APPLE_ENVIRONMENT=Sandbox`, le bundle attendu et les produits mensuel/annuel autorisés. Utiliser uniquement les écrans/configurations sécurisés ; ne coller aucun secret, JWS ou identifiant personnel dans le suivi ou Git.
4. Préparer une lecture **en lecture seule** de la ligne `subscriptions` du compte test et, si nécessaire, du ledger `apple_subscription_events`, dans un outil DB autorisé. Relever seulement le statut, l'expiration, le type d'événement et le fait que la ligne attendue existe ; ne publier aucun identifiant brut.

Le fichier [`http/apple-server-notifications.http`](../../http/apple-server-notifications.http) montre la forme de la requête. Son JWS factice sert à constater un rejet sûr ; il ne remplace pas une notification signée par Apple.

## Scénarios

1. **Notification de test Apple** — Depuis l'outil officiel disponible, demander une notification de test Sandbox vers l'URL enregistrée. Vérifier une réponse HTTP **204 du callback Apple** et une entrée ledger de type `TEST`, sans changement de `subscriptions`. Si l'interface ne propose pas cette action, noter « non prouvé » et utiliser une voie Apple officiellement autorisée lors d'une session ultérieure ; ne pas inférer le 204 depuis `/health`.
2. **Achat mensuel** — Sur l'iPhone, acheter le produit mensuel avec le testeur Sandbox, puis ouvrir l'accès Premium dans Cloudbreak. Attendu : `plan=premium`, statut `trial` ou `active`, expiration future ; la lignée appartient au compte test. Confirmer la ligne et la réception de l'événement correspondant séparément. Ne pas supposer que l'accusé de réception du test `TEST` l'a créée.
3. **Renouvellement accéléré** — Sur l'iPhone et le compte Sandbox, attendre le renouvellement accéléré prévu par Apple ; vérifier que `DID_RENEW` met à jour l'expiration vers une date plus récente et laisse Premium actif. Comparer l'état avant/après en lecture seule.
4. **Expiration** — Laisser le cycle Sandbox aller jusqu'à l'expiration effective, puis vérifier `EXPIRED`, le statut `expired` et le retour au quota non Premium. Une simple notification `DID_FAIL_TO_RENEW` ou `GRACE_PERIOD_EXPIRED` est ledger-only et ne suffit pas à conclure que l'accès a expiré.
5. **Remboursement** — Déclencher le scénario de remboursement par les moyens Sandbox prévus par Apple et attendre `REFUND`. Attendu : statut `revoked`, expiration effective à la date de révocation et perte d'accès Premium. Si Apple émet ensuite `REFUND_REVERSED`, vérifier le rétablissement du droit sur la transaction valide.
6. **Restauration** — Sur l'iPhone, restaurer l'achat sur le même compte permanent. Attendu : droit Premium retrouvé si la transaction Apple est encore valide ; aucun transfert vers un autre compte Cloudbreak. Une tentative depuis un autre compte doit rester en conflit.
7. **Préférence mensuel → annuel** — Sur l'iPhone, demander le changement de formule Sandbox. À `DID_CHANGE_RENEWAL_PREF`, attendre un **204 et une trace ledger uniquement**, sans changement immédiat de `subscriptions`. Lorsque la nouvelle transaction annuelle devient effective et qu'un événement de droit est reçu/vérifié, vérifier le droit et l'expiration correspondants. La table ne stocke pas la cadence mensuelle/annuelle : confirmer le produit auprès d'Apple, pas par une colonne `subscriptions` inexistante.

## Cas limites

- **Doublon** : un même `notificationUUID` livré deux fois ne crée pas deux effets ; le callback reste acquitté. Vérifier sans publier l'UUID.
- **Notification retardée** : un événement signé plus ancien ne doit pas écraser un statut ou une expiration plus récente. Vérifier l'ordre des états avec des horodatages non identifiants.
- **Révocation familiale** : `REVOKE` avec date de révocation vérifiée retire le droit Premium au membre concerné. Vérifier `revoked` et le quota non Premium.
- **Transaction manquante ou invalide** : un événement sans transaction imbriquée est consigné sans projection ; un JWS ou une transaction invalide est rejeté sans accorder de droit.

## Checklist finale

- [ ] URL Sandbox relue, Version 2 explicitement vérifiée si l'interface ou l'API Apple le permet ; Production laissée sans URL.
- [ ] Notification `TEST` réellement envoyée, callback HTTP 204 observé, ledger `TEST` présent, droit inchangé.
- [ ] Au moins un événement modifiant le droit réellement reçu, ligne `subscriptions` comparée avant/après en lecture seule.
- [ ] Achat, renouvellement, expiration, remboursement, restauration et changement de préférence contrôlés sur iPhone réel.
- [ ] Doublon, retard et révocation familiale vérifiés ou laissés explicitement « à tester ».
- [ ] Aucune preuve enregistrée ne contient d'email, de secret, de JWS, d'identifiant brut ou de log brut.

Tout résultat manquant reste « non prouvé ». Reporter la date, le scénario et les seuls statuts observés dans le suivi du chantier.
