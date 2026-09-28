# Guide de test manuel — quota invité et rate limit

## Prérequis

1. Démarrer les services : `cd backend && source .venv/bin/activate && make dev`.
2. Ouvrir `http/score-quota.http` dans VS Code avec l'extension REST Client et choisir
   l'environnement `local`.
3. Préparer dans `.vscode/settings.json` les JWT `guestFirst-jwt`, `guestRotated-jwt`,
   `premiumEmail-jwt` et `proEmail-jwt`. Les deux JWT `guest*` doivent provenir de deux sessions
   anonymes distinctes, créées par les requêtes de `http/auth.http`.
4. Remplacer `@testDate` par une date proche encore couverte par les prévisions Open-Meteo
   (aujourd'hui ou dans son horizon disponible). Cette date est envoyée au calcul du score ; elle
   ne décide jamais de la clé Redis de quota.

## Reset ciblé, sans toucher aux autres développeurs

Ne jamais lancer `FLUSHDB` sur un Redis partagé. Pour supprimer uniquement le quota de
l'installation du fichier HTTP :

```bash
INSTALLATION_ID='550e8400-e29b-41d4-a716-446655440000'
QUOTA_DATE=$(date -u +%F)
INSTALLATION_HASH=$(printf '%s' "$INSTALLATION_ID" | shasum -a 256 | awk '{print $1}')
docker exec cloudbreak-redis redis-cli DEL "quota:installation:${INSTALLATION_HASH}:${QUOTA_DATE}"
```

`QUOTA_DATE` est la date UTC actuelle du serveur, obtenue au moment du test. Elle est différente
de `@testDate` : le serveur utilise `datetime.now(UTC)`, non le paramètre `date`, pour le quota.
Le quota du JWT est indépendant : si ce JWT a déjà consommé son sommet du jour, créer un JWT
anonyme frais avant de relancer le scénario. Pour la limite IP, attendre la prochaine frontière de
minute plutôt que de supprimer une clé qui pourrait servir à quelqu'un d'autre.

## Scénarios à exécuter

### 1. Invité valide puis rotation du JWT

1. Exécuter `7.1` dans `http/score-quota.http` avec `guestFirst-jwt` et `@installationId`.
2. Vérifier `200` et une réponse score.
3. Exécuter `7.2` avec `guestRotated-jwt`, le même `@installationId` et un autre sommet.
4. Vérifier `429` et `detail.code = QUOTA_EXCEEDED`.

Le deuxième JWT ne doit donc pas réinitialiser le quota de l'installation.

### 2. En-tête d'installation invalide

1. Exécuter `7.3` (en-tête absent).
2. Vérifier `400` et `detail.code = INSTALLATION_ID_INVALID`.
3. Exécuter `7.4` (UUID version 1, donc pas version 4).
4. Vérifier le même `400 INSTALLATION_ID_INVALID`.

### 3. Limite de rafale

1. Terminer d'abord les scénarios invités 7.1 et 7.2. Ils consomment déjà deux appels de la
   fenêtre IP courante.
2. Attendre la **prochaine frontière de minute UTC** (`date -u +%S` doit revenir à `00`) sans
   envoyer d'autre score invité entre-temps. Cette attente crée une fenêtre IP propre.
3. Exporter un JWT anonyme frais dans le terminal local :

   ```bash
   export GUEST_JWT='copier-ici-un-jwt-anonyme-frais'
   export TEST_SCORE_DATE='remplacer-par-la-date-proche-de-testDate'
   export RATE_INSTALLATION_ID='123e4567-e89b-42d3-a456-426614174000'
   ```

4. Dès la frontière atteinte, envoyer les 60 requêtes suivantes. Les réponses doivent toutes être
   `200` ; le même sommet ne consomme pas de nouveau quota :

   ```bash
   for attempt in {1..60}; do
     curl --silent --output /dev/null --write-out "%{http_code}\n" \
       -H "Authorization: Bearer $GUEST_JWT" \
       -H "X-Cloudbreak-Installation-Id: $RATE_INSTALLATION_ID" \
       "http://localhost:8000/api/v1/score?peak_id=0728f7c7-a0c9-5fb0-b87d-d9edc8696840&date=$TEST_SCORE_DATE&hour=10"
   done
   ```

5. Avant la frontière de minute suivante, envoyer immédiatement une 61e fois (ou exécuter `7.8`
   une fois dans REST Client avec les mêmes JWT/UUID/IP) :

   ```bash
   curl --silent --output /dev/null --write-out "%{http_code}\n" \
     -H "Authorization: Bearer $GUEST_JWT" \
     -H "X-Cloudbreak-Installation-Id: $RATE_INSTALLATION_ID" \
     "http://localhost:8000/api/v1/score?peak_id=0728f7c7-a0c9-5fb0-b87d-d9edc8696840&date=$TEST_SCORE_DATE&hour=10"
   ```

6. Vérifier `429` et `detail.code = RATE_LIMIT_EXCEEDED` si la réponse est inspectée dans REST
   Client. Si la minute a changé pendant la boucle, recommencer depuis une frontière fraîche : le
   résultat ne serait plus concluant.

### 4. Validation et abonnements payants

1. Exécuter `7.5` avec le token Premium et vérifier `422` pour `date=pas-une-date`.
2. Exécuter `7.6` avec le token Premium, sans en-tête d'installation ; vérifier `200`.
3. Exécuter `7.7` avec le token Pro, sans en-tête d'installation ; vérifier `200`.

## Cas limites à garder en tête

- Le quota expire à minuit UTC du serveur, quel que soit le jour demandé dans `@testDate`.
- Un UUID valide mais différent représente une autre installation et a son propre quota.
- Une fois la minute écoulée, le compteur de rate limit repart dans une nouvelle fenêtre fixe.
- Le header invité est contrôlé après le bypass Premium/Pro : son absence n'empêche pas un compte
  payant de consulter un score.
- Un client modifié peut changer son UUID ; ce mécanisme est une atténuation, pas une preuve
  d'intégrité de l'app.

## Checklist finale

- [ ] Invité UUID v4 valide : `200`.
- [ ] Même installation, nouveau JWT, nouveau sommet : `429 QUOTA_EXCEEDED`.
- [ ] Header absent : `400 INSTALLATION_ID_INVALID`.
- [ ] UUID non-v4 : `400 INSTALLATION_ID_INVALID`.
- [ ] 61e appel invité dans la même minute : `429 RATE_LIMIT_EXCEEDED`.
- [ ] Date invalide : `422`.
- [ ] Premium sans header : `200`.
- [ ] Pro sans header : `200`.
- [ ] Aucun `FLUSHDB` exécuté.
