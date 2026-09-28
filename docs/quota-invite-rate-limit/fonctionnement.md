# Quota invité et limite de requêtes

## Le problème, en mots simples

Une session invitée Supabase peut être recréée facilement. Si le quota gratuit était attaché
uniquement au JWT, une personne pourrait créer un nouveau JWT à chaque consultation et obtenir
autant de sommets qu'elle le souhaite.

L'application envoie donc aussi un identifiant d'installation dans
`X-Cloudbreak-Installation-Id`. Pour un invité, cet identifiant doit être un UUID version 4.
Le serveur n'enregistre pas sa valeur en clair : il la hache avant de construire la clé Redis.

## Ce qui se passe à chaque demande de score

Les comptes Premium et Pro passent immédiatement : ils n'ont pas de quota et n'ont pas besoin de
l'en-tête d'installation. Pour une session gratuite, le serveur applique les contrôles suivants.

```text
GET /api/v1/score + JWT
          |
          v
JWT valide ? ------------------------------ non --> 401 / 403
          |
          v
Premium ou Pro actif ? -------------------- oui --> score 200
          |
          non (freemium)
          |
          +-- invité ? -- non --> quota du compte JWT --> score 200 ou 429 QUOTA_EXCEEDED
          |
          oui
          |
          v
UUID v4 dans X-Cloudbreak-Installation-Id ? -- non --> 400 INSTALLATION_ID_INVALID
          |
          oui
          |
          v
moins de 60 appels de cette IP dans la minute ? -- non --> 429 RATE_LIMIT_EXCEEDED
          |
          oui
          |
          v
quota de l'installation, puis quota du JWT
          |
          +-- nouveau sommet après le premier --> 429 QUOTA_EXCEEDED
          +-- sommet déjà ouvert aujourd'hui --> score 200
```

Le quota est un ensemble Redis de sommets, pas un compteur d'heures. Une fois un sommet ouvert,
toutes ses heures restent accessibles jusqu'à minuit UTC. La date de sa clé est l'heure UTC du
serveur au moment de l'appel, pas le paramètre `date` demandé pour la prévision. Une nouvelle
installation possède son propre quota ; le changement de JWT sur la même installation ne le remet
pas à zéro.

## Données temporaires dans Redis

| But | Forme de clé | Durée |
|---|---|---|
| Quota du compte | `quota:<hash-du-user-id>:<YYYY-MM-DD>` | Jusqu'à minuit UTC |
| Quota de l'installation invitée | `quota:installation:<hash-de-l-uuid>:<YYYY-MM-DD>` | Jusqu'à minuit UTC |
| Rafale d'un invité | `rate_limit:anonymous_score:<hash-ip>:<fenêtre>` | 60 secondes |

Les deux hachages évitent de mettre l'identifiant Supabase, l'UUID d'installation ou l'adresse IP
en clair dans les clés Redis et les logs associés.

## Fichiers concernés

| Fichier | Rôle |
|---|---|
| `app/core/dependencies.py` | Ordonne le bypass payant, la validation de l'UUID, la limite IP et les quotas. |
| `app/services/quota.py` | Garde un sommet gratuit par jour dans des SET Redis atomiques. |
| `app/services/rate_limit.py` | Compte les demandes invitées par IP dans une fenêtre fixe de 60 secondes. |
| `app/core/errors.py` | Stabilise les codes `INSTALLATION_ID_INVALID` et `RATE_LIMIT_EXCEEDED`. |
| `http/score-quota.http` | Fournit les appels manuels reproductibles. |

## Limites connues

Cette mesure empêche le contournement le plus simple, mais ne transforme pas le client en preuve
matérielle : une application modifiée peut fabriquer un nouvel UUID d'installation. La limite IP
atténue les rafales, mais une personne peut changer d'IP, partager une IP ou utiliser un proxy.
Une attestation d'application (App Attest sur iOS) est l'amélioration prévue pour rendre le signal
d'installation plus difficile à falsifier.
