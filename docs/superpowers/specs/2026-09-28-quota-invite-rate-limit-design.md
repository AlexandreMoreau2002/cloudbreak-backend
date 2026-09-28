# Design — quota invité : identifiant d’installation et rate-limit

## But

Empêcher qu’un utilisateur invité contourne le quota freemium d’un sommet par jour
en supprimant puis recréant sa session anonyme Supabase. Cette opération change
l’UUID Supabase et recrée actuellement un quota Redis vierge.

Cet étage rend le contournement coûteux sans prétendre apporter une preuve matérielle
d’identité. App Attest / DeviceCheck reste explicitement hors périmètre.

## Périmètre et non-objectifs

- Cible : `GET /api/v1/score` pour les sessions Supabase anonymes et freemium.
- Préserver le quota existant par `user_id`, le comportement des comptes permanents et
  le bypass Premium/Pro.
- Ne créer ni table SQL, ni endpoint supplémentaire, ni fingerprint matériel.
- Ne pas assurer de rétrocompatibilité avec un client invité qui n’envoie pas le signal :
  l’application n’est pas encore distribuée.

## Flux retenu

```
Premier lancement mobile
    |
    +-- SecureStore vide ? -- oui --> UUID v4 aléatoire, écrit dans le Keychain
    |                                      |
    +-- non -------------------------------+
                                           v
Chaque appel API : X-Cloudbreak-Installation-Id: <UUID>
                                           |
                                           v
GET /score + JWT invité --> validation UUID --> limite IP courte
                                           |
                                           v
                       quota user_id actuel + quota installation journalier
                                           |
                                           v
                                      score ou erreur 429
```

L’UUID est un identifiant aléatoire opaque, sans information matérielle, géographique ou
personnelle. Il est généré une seule fois, indépendamment de Supabase, puis gardé dans le
Keychain par `expo-secure-store`. Une réinitialisation de session Supabase ne le modifie pas.

## Comportement backend

1. Les comptes Premium/Pro conservent le bypass du quota fonctionnel existant.
2. Pour un invité freemium, le header `X-Cloudbreak-Installation-Id` est obligatoire et doit
   contenir un UUID v4 valide. Son absence ou son format invalide renvoie `400` avec le code
   `INSTALLATION_ID_INVALID` ; aucun quota n’est consommé.
3. Le backend applique un compteur Redis à fenêtre fixe de 60 secondes par adresse IP sur les
   requêtes invitées `/score`. Limite : 60 requêtes/minute. Cette valeur laisse passer le
   chargement parallèle de la vue semaine, tout en ralentissant fortement un client qui forge
   des identifiants d’installation. Un dépassement renvoie `429` avec `RATE_LIMIT_EXCEEDED`.
4. Le backend garde le quota Redis existant `quota:{user_id}:{date}` et applique le même service
   au signal d’installation, sous une clé distincte :
   `quota:installation:{sha256(installation_id)}:{date}`. L’UUID brut n’apparaît donc ni dans
   Redis ni dans les logs.
5. Le quota d’installation est vérifié avant celui du `user_id`, afin qu’une installation déjà
   épuisée ne consomme pas le quota neuf d’une session anonyme recréée.
6. Les deux quotas doivent autoriser la même consultation de sommet. Si l’un est déjà épuisé,
   la réponse reste `429 QUOTA_EXCEEDED`. Une consultation déjà autorisée pour le même sommet
   demeure disponible à toutes les heures, conformément au comportement existant.

En production, l’API n’est atteignable que via Traefik sur le réseau Docker interne. Uvicorn sera
configuré pour accepter les headers proxy seulement dans ce contexte (`--proxy-headers` et
`--forwarded-allow-ips=*`) ; Traefik est alors le seul émetteur possible du header vu par l’API.
En développement, sans header proxy, l’adresse du client de requête reste le repli. Les tests
couvrent le choix de l’adresse, sans faire confiance à un `X-Forwarded-For` sur une API exposée
directement.

## Comportement mobile

Un petit service dédié lit ou initialise l’UUID dans SecureStore. `apiFetch` ajoute le header à
toutes les requêtes authentifiées. Cette centralisation évite de modifier chaque service API et
garantit que le score reçoit systématiquement le signal. L’UUID ne sera jamais affiché ou loggé.

L’absence inattendue du signal local est réparée en générant un nouvel UUID avant la requête.
Si SecureStore devient indisponible, l’appel réseau est refusé localement avec une erreur claire
plutôt que d’émettre une requête incomplète qui serait rejetée par le backend.

## Tests et documentation attendus

- Backend : tests unitaires du service de quota/rate-limit et tests de flux HTTP : UUID absent,
  UUID mal formé, nouvelle session anonyme avec la même installation, limite IP, quotas et
  bypass Premium/Pro.
- Mobile : tests du service SecureStore et de l’ajout du header dans `apiFetch` sans exposer
  l’identifiant dans les logs.
- Validation complète : `make validate` et `npm run validate`.
- Documentation de story, guide de test manuel et enrichissement de `backend/http/score-quota.http`
  avec le succès, quota dépassé, header absent/invalide et payload de query invalide.
- Audit obligatoire par `cloudbreak-security`, puis revue Cloudbreak et vérification des imports
  avant la PR vers `develop` ; aucune fusion sans accord explicite.

## Évolution ultérieure

Si l’observation après lancement révèle une fraude significative, ajouter App Attest / DeviceCheck
pour attester que le signal provient d’une installation Apple authentique. Cette évolution pourra
remplacer ou renforcer le signal déclaratif sans modifier le quota fonctionnel déjà en place.
