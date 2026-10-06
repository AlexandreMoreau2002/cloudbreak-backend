# Apple Server Notifications — état DEV / Sandbox

État observé le 2026-10-06. Cette page sépare la configuration, le comportement attendu du code et la preuve d'un appel réel d'Apple. Le guide opérateur est dans [guide-test.md](apple-server-notifications/guide-test.md) et le flux technique dans [fonctionnement.md](apple-server-notifications/fonctionnement.md).

## Configuration observée

- Environnement ciblé : backend DEV, `ENVIRONMENT=development` et `APPLE_ENVIRONMENT=Sandbox` vérifiés par comparaison de configuration, sans publier leurs valeurs sensibles.
- Le `APPLE_BUNDLE_ID` DEV correspond à la valeur attendue. Le vérificateur exige également un bundle, l'environnement Apple et l'un des deux produits Cloudbreak autorisés.
- URL Sandbox enregistrée et relue dans App Store Connect : `https://dev-api.cloudbreak-app.com/api/v1/webhooks/apple`.
- URL Production non configurée. Aucun déploiement ni changement de variables d'environnement n'a été nécessaire.
- `/health` public DEV a répondu HTTP 200 et le service affichait 1/1 réplique. Cela établit sa disponibilité au moment du contrôle, pas la livraison d'une notification Apple.
- Le code traite les notifications App Store Server Notifications V2. L'interface App Store Connect inspectée n'exposait aucun sélecteur de version : **la sélection de Version 2 côté Apple n'est pas prouvée**.

Les paramètres non secrets à vérifier avant chaque essai sont `ENVIRONMENT`, `APPLE_ENVIRONMENT`, `APPLE_BUNDLE_ID`, l'URL Sandbox, les deux identifiants de produits autorisés dans le code et la disponibilité du backend DEV. Les clés Apple, identifiants de transaction et JWS ne doivent pas être copiés dans ce dépôt.

## Politique des événements

| Notification V2 vérifiée | Traitement prévu | Effet attendu sur le droit Premium |
| --- | --- | --- |
| `TEST` | Ledger d'idempotence, puis 204 | Aucun |
| `DID_CHANGE_RENEWAL_PREF`, `DID_FAIL_TO_RENEW`, `GRACE_PERIOD_EXPIRED` | Ledger uniquement, puis 204 | Aucun changement immédiat |
| `SUBSCRIBED`, `DID_RENEW`, `EXPIRED` | Vérification de la transaction imbriquée, ledger et projection | Statut et expiration mis à jour selon l'événement et la transaction |
| `REFUND`, `REVOKE`, `REFUND_REVERSED`, `RENEWAL_EXTENDED` | Vérification de la transaction imbriquée, ledger et projection | Révocation ou rétablissement/extension selon l'événement vérifié |

Un événement de droit sans transaction imbriquée passe dans le ledger sans projection. Les doublons sont sans effet supplémentaire. Le backend conserve `plan=premium`, le statut et deux dates distinctes : `expires_at` est la fin effective du droit (ramenée à `revocationDate` après remboursement/révocation), tandis que `apple_period_expires_at` garde la fin de la période payée vérifiée dans la transaction Apple. Une transaction d'une période strictement plus ancienne reste dans le ledger sans modifier le droit. Pour une même période, la date de signature du webhook empêche un renouvellement retardé d'annuler une révocation plus récente ; une vérification client ne peut pas non plus réactiver une période révoquée. Le backend ne stocke pas la périodicité mensuelle ou annuelle.

La migration ajoutant `apple_period_expires_at` est **en attente de déploiement** ; elle crée une colonne nullable sans reprise des lignes existantes. Pour une ancienne ligne non révoquée, le service emploie `expires_at` comme repère de période jusqu'à la prochaine transaction vérifiée. Une ancienne ligne révoquée ne déduit jamais la fin de période de sa date de révocation.

## Preuves opérationnelles distinctes

- Notification de test acquittée en 204: **not proved** — l'interface consultée n'offrait pas d'action d'envoi ; aucun test n'a été envoyé et aucun 204 de callback Apple n'a été observé.
- Événement modifiant subscriptions rejoué et ligne observée en lecture seule: **not proved** — aucun rejeu de cycle Sandbox n'était disponible dans l'interface consultée ; aucune requête de base n'a été exécutée.

La sauvegarde de l'URL et le `GET /health` ne démontrent ni la livraison du webhook, ni un changement de `subscriptions`. Une notification `TEST`, même acquittée, n'attribue jamais Premium. Les étapes de preuve manquantes sont dans le [guide de test manuel](apple-server-notifications/guide-test.md).
