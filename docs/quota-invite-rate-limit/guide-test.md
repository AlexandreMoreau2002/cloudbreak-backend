# Guide de test manuel — quota invité et rate limit

## Prérequis

1. Démarrer les services : `cd backend && source .venv/bin/activate && make dev`.
2. Ouvrir `http/score-quota.http` dans VS Code avec l'extension REST Client et choisir
   l'environnement `local`.
3. Préparer dans `.vscode/settings.json` les JWT `guestFirst-jwt`, `guestRotated-jwt`,
   `premiumEmail-jwt` et `proEmail-jwt`. Les deux JWT `guest*` doivent provenir de deux sessions
   anonymes distinctes, créées par les requêtes de `http/auth.http`.
4. Utiliser une date `@testDate` qui n'a pas encore servi pour les UUID d'installation du fichier,
   ou appliquer le reset ciblé ci-dessous.

## Reset ciblé, sans toucher aux autres développeurs

Ne jamais lancer `FLUSHDB` sur un Redis partagé. Pour supprimer uniquement le quota de
l'installation du fichier HTTP :

```bash
INSTALLATION_ID='550e8400-e29b-41d4-a716-446655440000'
TEST_DATE='2026-04-01'
INSTALLATION_HASH=$(printf '%s' "$INSTALLATION_ID" | shasum -a 256 | awk '{print $1}')
docker exec cloudbreak-redis redis-cli DEL "quota:installation:${INSTALLATION_HASH}:${TEST_DATE}"
```

Le quota du JWT est indépendant : pour un test entièrement neuf, créer aussi un nouveau JWT
anonyme. Pour la limite IP, attendre la prochaine fenêtre de 60 secondes ; cela évite de supprimer
une clé qui pourrait servir à quelqu'un d'autre.

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

1. Attendre le début d'une minute ou attendre 60 secondes depuis le dernier essai de rate limit.
2. Exécuter `7.8` 60 fois dans la même minute, sans modifier le JWT, l'UUID ou le réseau.
3. Vérifier que les 60 réponses sont `200` : le même sommet ne consomme pas de nouveau quota.
4. Exécuter une 61e fois avant la fin de cette même minute.
5. Vérifier `429` et `detail.code = RATE_LIMIT_EXCEEDED`.

### 4. Validation et abonnements payants

1. Exécuter `7.5` avec le token Premium et vérifier `422` pour `date=pas-une-date`.
2. Exécuter `7.6` avec le token Premium, sans en-tête d'installation ; vérifier `200`.
3. Exécuter `7.7` avec le token Pro, sans en-tête d'installation ; vérifier `200`.

## Cas limites à garder en tête

- Rejouer le même sommet à une autre heure doit rester autorisé jusqu'à minuit UTC.
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
