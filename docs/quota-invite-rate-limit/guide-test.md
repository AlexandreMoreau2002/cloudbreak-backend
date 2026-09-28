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
2. Préparer un **JWT anonyme fraîchement créé** et un UUID v4 d'installation jamais utilisés.
   Cette paire neutralise les deux quotas de sommet avant la première requête : le nouveau JWT n'a
   pas de quota utilisateur consommé et la nouvelle installation n'a pas de quota installation
   consommé. Ne lancer aucun autre score invité depuis cette IP après le départ du script.
3. Exporter les valeurs dans le terminal local. `TEST_SCORE_DATE` doit être la même date proche et
   couverte par Open-Meteo que `@testDate` :

   ```bash
   export GUEST_JWT='copier-ici-un-jwt-anonyme-frais'
   export TEST_SCORE_DATE='remplacer-par-la-date-proche-de-testDate'
   export RATE_INSTALLATION_ID='123e4567-e89b-42d3-a456-426614174000'
   ```

4. Lancer ce script auto-validant. Il attend lui-même la prochaine frontière de minute, mémorise
   sa fenêtre epoch, puis abandonne avec `INVALID` si elle change avant la 61e réponse. Il exige
   60 réponses `200` sans code `RATE_LIMIT_EXCEEDED`, puis une 61e réponse `429` contenant ce
   code. Le même sommet est volontairement rejoué : il ne consomme pas de quota supplémentaire.

   ```bash
   set -eu
   BODY_DIR=$(mktemp -d)
   trap 'rm -rf "$BODY_DIR"' EXIT
   PEAK_ID='0728f7c7-a0c9-5fb0-b87d-d9edc8696840'
   SCORE_URL="http://localhost:8000/api/v1/score?peak_id=$PEAK_ID&date=$TEST_SCORE_DATE&hour=10"

   # Ne jamais réutiliser la fenêtre où les scénarios 7.1/7.2 ont été joués.
   OLD_WINDOW=$(( $(date +%s) / 60 ))
   while [ $(( $(date +%s) / 60 )) -eq "$OLD_WINDOW" ]; do sleep 0.1; done
   TARGET_WINDOW=$(( $(date +%s) / 60 ))
   echo "Fenêtre fraîche démarrée : $TARGET_WINDOW"

   for ATTEMPT in {1..60}; do
     if [ $(( $(date +%s) / 60 )) -ne "$TARGET_WINDOW" ]; then
       echo "INVALID: frontière de minute franchie avant l'appel $ATTEMPT" >&2
       exit 1
     fi
     BODY="$BODY_DIR/$ATTEMPT.json"
     STATUS=$(curl --silent --output "$BODY" --write-out '%{http_code}' \
       -H "Authorization: Bearer $GUEST_JWT" \
       -H "X-Cloudbreak-Installation-Id: $RATE_INSTALLATION_ID" "$SCORE_URL")
     if [ "$STATUS" != 200 ] || rg -q 'RATE_LIMIT_EXCEEDED' "$BODY"; then
       echo "FAIL: appel $ATTEMPT, HTTP $STATUS (attendu : 200 sans RATE_LIMIT_EXCEEDED)" >&2
       exit 1
     fi
   done

   if [ $(( $(date +%s) / 60 )) -ne "$TARGET_WINDOW" ]; then
     echo "INVALID: frontière de minute franchie avant le 61e appel" >&2
     exit 1
   fi
   LAST_BODY="$BODY_DIR/61.json"
   LAST_STATUS=$(curl --silent --output "$LAST_BODY" --write-out '%{http_code}' \
     -H "Authorization: Bearer $GUEST_JWT" \
     -H "X-Cloudbreak-Installation-Id: $RATE_INSTALLATION_ID" "$SCORE_URL")
   if [ $(( $(date +%s) / 60 )) -ne "$TARGET_WINDOW" ]; then
     echo "INVALID: frontière de minute franchie pendant le 61e appel" >&2
     exit 1
   fi
   if [ "$LAST_STATUS" != 429 ] || ! rg -q 'RATE_LIMIT_EXCEEDED' "$LAST_BODY"; then
     echo "FAIL: 61e appel, HTTP $LAST_STATUS (attendu : 429 RATE_LIMIT_EXCEEDED)" >&2
     exit 1
   fi
   echo 'PASS: 60 réponses 200, puis 61e réponse 429 RATE_LIMIT_EXCEEDED dans la même fenêtre.'
   ```

5. Considérer uniquement le résultat `PASS` comme concluant. Un résultat `INVALID` signifie que
   la fenêtre a tourné : recommencer avec un JWT/UUID frais, au lieu d'interpréter les statuts.

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
