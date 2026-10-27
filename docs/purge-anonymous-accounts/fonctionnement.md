# Purge automatique des comptes anonymes inactifs — comment ça marche

## L'idée en une image

Imagine une consigne de gare. Quelqu'un dépose un sac sans laisser son nom, juste un ticket.
S'il perd le ticket, plus personne ne peut venir réclamer le sac : il reste là pour toujours.

Dans Cloudbreak, c'est pareil :

- le **ticket**, c'est la session Supabase anonyme (un `user_id` sans email) ;
- le **sac**, ce sont les données qu'elle laisse chez nous : les scores consultés (`predictions`),
  les validations terrain (`terrain_validations`) et les favoris (`user_favorites`) ;
- si l'app est réinstallée ou le téléphone changé, le ticket est perdu. Personne ne peut plus
  demander la suppression (pas d'email pour prouver que c'est bien lui).

La règle du RGPD dit : on ne garde pas des données dont on n'a plus besoin. Alors, chaque nuit,
un gardien fait le tour de la consigne et vide les casiers **anonymes** qui n'ont pas bougé
depuis **30 jours**.

## Le gardien ne se trompe pas de casier : la double garde

1. **Le badge du gardien** : l'endpoint n'est appelable qu'avec le secret du cron
   (`X-Cron-Secret` = `INTERNAL_CRON_SECRET`). Ni l'app, ni un utilisateur, même connecté, ne
   peut le déclencher.
2. **La vérification de l'étiquette** : avant de vider un casier, le gardien demande à Supabase
   « ce compte est-il bien anonyme ? ». Il ne supprime que si la réponse est **exactement**
   `is_anonymous: true`. Un compte permanent (avec email ou Apple) n'est **jamais** supprimé,
   même s'il est inactif depuis un an.

Et avant même de demander à Supabase, il écarte tous les `user_id` qui ont une ligne `users`
(un compte provisionné = un compte permanent) : c'est un préfiltre bon marché.

## Le flux

```
cron VPS (04:00 Europe/Paris)
   |  POST /internal/maintenance/purge-anonymous[?dry_run=true]
   |  X-Cron-Secret: ****
   v
require_cron_secret ---- secret absent / < 32 car. ----> 503 INTERNAL_JOBS_DISABLED
   |                ---- secret faux / JWT seul -------> 403 INTERNAL_AUTH_FAILED
   v
SUPABASE_URL + SERVICE_ROLE_KEY posés ? -- non --> 503 SERVICE_UNAVAILABLE
   |
   v
dry_run ? ── oui ──> pas de verrou (rien n'est écrit) ──────────────┐
   | non                                                             |
   v                                                                 |
SET lock:anon-purge <jeton unique> NX EX 300                         |
   ├─ déjà pris (une autre purge tourne)                             |
   |      -> 200 {tout à 0, "skipped_locked": 1}, on s'arrête        |
   v                                                                 |
fetch_candidates <───────────────────────────────────────────────────┘ (UNE requête SQL)
   predictions.created_at  ┐
   terrain_validations.validated_at ├─ UNION ALL ─> MAX(date) par user_id
   user_favorites.created_at ┘
   + pas de ligne users      + MAX(date) < maintenant - 30 j
   + les plus anciens d'abord + LIMIT 200
   |
   v
pour chaque candidat ───────────────────────────────────────────────┐
   |                                                                  |
   GET {SUPABASE}/auth/v1/admin/users/{id}                            |
   |                                                                  |
   ├─ erreur réseau / 5xx / 404 sans user_not_found / JSON bizarre    |
   |      -> errors += 1, on NE TOUCHE À RIEN, candidat suivant ──────┤
   ├─ is_anonymous n'est pas strictement true                         |
   |      -> skipped_not_anonymous += 1, on NE TOUCHE À RIEN ─────────┤
   ├─ 404 user_not_found (déjà parti de Supabase)                     |
   |      -> étape 2 seulement (local)                                |
   └─ is_anonymous == true                                            |
          (en dry_run : aucune suppression, on compte juste) ─────────┤
          1. delete_supabase_user (compte Supabase)                   |
             échec -> errors += 1, RIEN de local supprimé ────────────┤
                      (le candidat sera rejoué la nuit suivante)      |
          2. delete_user_data (DB)                                    |
             échec -> rollback, errors += 1 ──────────────────────────┤
                      (nuit suivante : Supabase répond 404            |
                       user_not_found -> étape 2 seule = réparé)      |
          3. QuotaService.delete_user_keys (Redis, best-effort)       |
          purged += 1 ────────────────────────────────────────────────┘
   |
   v
logger.info("anonymous_purge_done", compteurs)
libération du verrou (compare-et-supprime : seulement si c'est encore NOTRE jeton)
200 {"candidates", "purged", "skipped_not_anonymous", "errors", "dry_run", "skipped_locked"}
```

### Pourquoi Supabase d'abord ?

Pense à un déménagement : on rend d'abord les clés au propriétaire (Supabase), puis on vide
l'appartement (nos tables). Si le propriétaire n'est pas joignable, on ne vide rien et on revient
demain. Si on a rendu les clés mais que le camion tombe en panne, demain le propriétaire dira
« ce locataire n'existe plus » (404 `user_not_found`) et on finira de vider : ça se répare tout
seul. Dans l'ordre inverse, on aurait pu vider l'appartement sans jamais rendre les clés
(compte Supabase orphelin, plus jamais retrouvé puisqu'il n'a plus de données chez nous).

### Pourquoi un verrou ?

Si le cron et un lancement manuel partent en même temps, les deux traiteraient les mêmes
candidats et doubleraient les appels à l'API Admin Supabase. Le verrou Redis
`lock:anon-purge` (jeton unique, 5 min max) laisse passer une seule purge réelle ; l'autre
répond tout de suite `skipped_locked: 1`. Le verrou est rendu à la fin, même en cas d'erreur, et
seulement s'il nous appartient encore. Le dry_run ne prend pas le verrou : il n'écrit rien.

Aucun identifiant n'apparaît ni dans la réponse, ni dans les logs : seulement des compteurs.

## Les fichiers

| Fichier | Rôle |
|---------|------|
| `app/api/v1/endpoints/internal_maintenance.py` | Route `POST /internal/maintenance/purge-anonymous` (secret cron, 503 si Supabase Admin non configuré) |
| `app/services/anonymous_purge.py` | Sélection des candidats (`build_candidates_query`) et boucle de purge (`PurgeSummary`) |
| `app/core/security.py` | `get_supabase_user` (lecture Admin) + `SupabaseAdminError` ; `delete_supabase_user` réutilisé |
| `app/services/user.py` | `delete_user_data` réutilisé (story 2.4b) |
| `app/services/quota.py` | `QuotaService.delete_user_keys` réutilisé |
| `app/core/config.py`, `.env.example` | `ANON_RETENTION_DAYS` (30), `ANON_PURGE_MAX_PER_RUN` (200) |
| `app/main.py` | Enregistrement du router (tag `internal`) |
| `tests/test_anonymous_purge.py`, `tests/test_security.py`, `tests/test_api_internal_maintenance.py`, `tests/features/test_feature_purge_anonymous_flow.py` | Tests |
| `http/maintenance.http` | Requêtes REST Client |

## Les décisions

- **30 jours** d'inactivité : décidé par Alexandre le 2026-10-27, à faire valider juridiquement
  et à citer dans la politique de confidentialité (ops, section 6).
- **« Activité »** = la date la plus récente parmi `predictions.created_at`,
  `terrain_validations.validated_at` et `user_favorites.created_at`.
- **Plafond** de 200 comptes par appel (`ANON_PURGE_MAX_PER_RUN`) : borne la durée de l'appel et
  le nombre d'appels à l'API Admin Supabase. Les plus anciens passent en premier ; le reste
  passe les nuits suivantes.
- **dry_run** : mêmes décisions (y compris les appels de lecture Supabase), aucune suppression.
  `purged` compte alors ce qui *serait* purgé. À lancer avant la première purge réelle.
- **Idempotent** : relancer ne fait rien de plus. Un candidat purgé n'a plus de données, il
  n'est donc plus sélectionné ; un compte déjà supprimé chez Supabase (404 `user_not_found`)
  est traité comme « déjà parti » et seules ses données locales sont effacées.
- **Un échec n'arrête pas les autres** : chaque candidat est traité indépendamment.
- **Ordre** : compte Supabase d'abord, données locales ensuite (inverse de `DELETE /api/v1/user`,
  où l'utilisateur est présent pour rejouer) : un échec n'importe où se répare au passage suivant.
- **Verrou** `lock:anon-purge` : même mécanique que `lock:favorite-alerts` (SET NX + jeton +
  libération par script compare-et-supprime), TTL 300 s. Le TTL est un filet de sécurité :
  un passage très lent (Supabase qui répond en limite de timeout sur 200 candidats) peut le
  dépasser ; un second passage pourrait alors démarrer, sans risque puisque tout est idempotent.

## Limites connues

- Un anonyme qui utilise l'app sans rien écrire (pas de score calculé, pas de favori ajouté)
  pendant 30 jours mais garde des favoris anciens est considéré inactif : ses favoris et son
  compte anonyme sont supprimés, sa session devient invalide (l'app repart sur une nouvelle
  session anonyme).
- Fenêtre de course minime : un anonyme qui redevient actif entre la sélection et la
  suppression (quelques secondes) peut être purgé.
- `candidates` est plafonné par `max_per_run` : il ne donne pas le stock total en attente.

## Ce qui n'est PAS purgé

- Les comptes Supabase anonymes **sans aucune donnée chez nous** (ils ne sont jamais
  candidats : rien à minimiser côté Cloudbreak).
- Les `apple_subscription_events` sans `original_transaction_id` (non rattachables à un
  utilisateur ; un anonyme ne peut de toute façon pas acheter : `verify` exige un compte permanent).
- Les clés `quota:installation:*` (hash d'installation, expirent seules) et les journaux serveur.
