# Cloudbreak — Audit produit

_Dernière mise à jour : 2026-07-26_

---

## C'est quoi Cloudbreak

Une app iOS qui répond à une seule question :
**"Est-ce que je vais voir une mer de nuage depuis ce sommet, à cette heure ?"**

L'utilisateur cherche un sommet, choisit une date et une heure, et reçoit une probabilité (0-100%) avec un verdict (`high` / `medium` / `low` / `none`).

L'algorithme tourne côté serveur — il peut être amélioré sans mise à jour de l'app.

---

## Ce qui est fonctionnel aujourd'hui

### Backend — opérationnel en local

| Fonctionnalité | État |
|----------------|------|
| API score mer de nuage | ✅ Fonctionne en vrai |
| Données météo Open-Meteo | ✅ Appel réel (gratuit, sans clé) |
| Cache Redis 10 min | ✅ Actif |
| Auth JWT Supabase | ✅ Validé localement |
| Dataset sommets seedé depuis `app/db/peaks_data.json` (23 782 entrées source) | ✅ |
| Index idx_peaks_name | ✅ Migration Alembic |
| Script génération Overpass API + Open-Meteo elevation | ✅ scripts/generate_peaks.py |
| Script enrichissement `region` sans régénération complète | ✅ scripts/enrich_region.py |
| Migrations DB | ✅ Alembic |
| Tests automatisés backend | ✅ `make validate` |
| CI pipeline | ✅ GitHub Actions |
| Domain layer (`app/domain/`) — logique métier pure (zero I/O) | ✅ Refactorisé |
| Contrat score présentation — `label_code`, `context_code`, `context_params`, fenêtre, stabilité | ✅ Story 3.5 |
| i18n score côté mobile — backend renvoie codes stables, traduction dans le front uniquement | ✅ Refacto i18n |
| Onboarding mobile narratif (story 7.1) : splash + transition mer de nuages + 3 écrans, gate AsyncStorage, permissions, sommet par défaut via API publique | ✅ |

| Recherche sommets (`GET /api/v1/peaks/search` + `GET /api/v1/peaks/{slug}`) | ✅ ILIKE, limit 20 — **publics depuis story 7.1** (onboarding pré-login, aucun JWT requis) |
| Favoris (`POST/DELETE/GET /api/v1/user/favorites`) | ✅ Avec peak info jointe |
| Quota freemium Redis — 1 sommet unique/jour, bypass Premium/Pro, reset minuit UTC | ✅ Story 4.1 |
| `make seed-test` / `make unseed-test` — users de test Supabase (freemium, pro) | ✅ Story 4.1 |
| `make clean-subscriptions` / `make reset-db` — maintenance DB dev | ✅ Story 4.1 |
| Suppression compte RGPD (`DELETE /api/v1/user/`) — suppression DB + Supabase Auth → 204, compte permanent requis | ✅ Story 2.4 |
| Provisioning compte permanent (`POST /api/v1/user/provision`) — projection `users` idempotente (get-or-create) à la conversion depuis une session anonyme | ✅ Stories 2.5/2.6 — JWT permanent requis (403 `ACCOUNT_REQUIRED` si anonyme) |
| Profil / état sondage (`GET /api/v1/user/me`) — expose `is_anonymous`, `provisioned`, `survey_completed_at`, `survey_skipped_at` | ✅ Stories 2.5/2.8 |
| Mini-sondage post-création (`PATCH /api/v1/user/survey`) — `acquisition_source`, `practice`, `newsletter_opt_in` ou `skipped`, colonnes typées de `users`, terminal + idempotent | ✅ Story 2.8 — JWT permanent requis |
| Retrait consentement newsletter (`PATCH /api/v1/user/preferences`) — `newsletter_opt_in` booléen, non terminal (modifiable dans les deux sens, RGPD art. 7-3) | ✅ Stories 2.5/2.8 — JWT permanent requis (403 `ACCOUNT_REQUIRED` si anonyme) |
| Favoris — refus explicite d'une session anonyme (403 `ACCOUNT_REQUIRED`) | ✅ Stories 2.5/3.3 |
| Instrumentation analytics — `track()` stub DEBUG-only sur `score_calculated`, `quota_bypassed`, `quota_exceeded`, `favorite_added/removed`, `account_deleted` (story 1.7) | ✅ Stub, aucun réseau |
| Validation terrain (`POST /api/v1/validations`) — confirmation/infirmation d'une prédiction, persistance `Prediction` best-effort à chaque `GET /api/v1/score`, table `terrain_validations` (`result`, `lat`/`lng` optionnels) (story 6.1) | ✅ Sans photo — voir story 6.2 |
| JWT Supabase — vérification `issuer`/`audience` en plus de la signature ECC (2026-09-12) | ✅ `decode_supabase_jwt` prend `supabase_url`, rejette `aud`/`iss` invalides ou absents |

### Ce qui n'existe pas encore

- Gestion des abonnements StoreKit 2 (vérification reçus, table `subscriptions`) — story 4.3
- Photo optionnelle sur validation terrain + calcul du taux de précision — story 6.2
- Notifications push
- Déploiement VPS (infra prod)
- Analytics PostHog réel (le backend expose uniquement le stub d'instrumentation)

---

## Comment fonctionne le score — version non-technique

### La question de fond

Une mer de nuage se forme quand :
1. Il y a des nuages **bas** (dans les vallées)
2. Le sommet est **au-dessus** de ces nuages
3. L'air froid humide est **piégé** en bas par une couche d'air chaud au-dessus (inversion thermique)
4. Le vent est **faible** (sinon les nuages se dispersent)

L'algorithme mesure ces 4 conditions + la pression atmosphérique, les combine, et donne une probabilité.

### Les données utilisées

Toutes les données viennent de **Open-Meteo** — une API météo gratuite, sans clé, qui fournit des prévisions jusqu'à 16 jours à l'avance avec une résolution d'environ 1 à 5km.

Pour chaque sommet, on récupère les données à **4 altitudes différentes** (925 hPa ≈ 800m, 850 hPa ≈ 1500m, 800 hPa ≈ 1950m, 700 hPa ≈ 3000m) pour reconstruire ce qui se passe dans la colonne d'air.

### Règles absolues (hard gates)

- Si la base des nuages est **au-dessus** du sommet → **0%, sans calcul**.
- Si `cloud_cover_low < 45%` → **0%, sans calcul**.

Exemples :
- sommet à 1720m, nuages qui commencent à 2500m → l'observateur est sous les nuages → mer de nuage impossible → 0%
- nuages bas à 20% seulement → couche trop fragmentée → pas de scénario crédible → 0%

Le verdict `none` est donc un état produit distinct de `low`.

### Seuil complémentaire sur `high`

Même quand le calcul est autorisé, le verdict `high` demande une couche basse plus franche :

- sous `55%` de `cloud_cover_low`, un `high` n'est pas retourné
- entre `45%` et `54%`, le backend peut encore retourner `low` ou `medium`

### Les 5 indicateurs

| Indicateur | Poids | Ce qu'il mesure |
|------------|-------|-----------------|
| Base des nuages | 35% | Les nuages sont-ils sous le sommet ? |
| Inversion thermique | 20% | L'air froid est-il piégé dans les vallées ? |
| Humidité | 20% | L'air est-il assez humide pour former des nuages ? |
| Vent | 15% | Le vent est-il assez faible pour laisser les nuages en place ? |
| Pression | 10% | L'anticyclone stabilise-t-il le temps ? |

### Malus saisonnier

Supprimé — la présence ou l'absence de nuages bas détermine le verdict directement. Pas de coefficient saisonnier dans la version actuelle.

---

## Fiabilité actuelle de l'algorithme

### Ce qui est solide

- La méthode de calcul de la base des nuages (Skew-T) est validée météorologiquement
- L'inversion thermique est le vrai signal physique des mers de nuage
- Open-Meteo est une source de données fiable et maintenue

### Ce qui est fragile

- **Les poids (35/20/20/15/10) sont arbitraires** — ils n'ont jamais été calibrés sur des observations réelles. Un score de 75% peut être faux.
- **Pas de retour terrain** — aucune donnée réelle pour valider que le score colle à la réalité.
- **Résolution spatiale limitée** — pour un petit sommet isolé, les données météo représentent une zone de plusieurs km², pas exactement le sommet.

### Ce qu'il faudrait pour améliorer

Collecter ~50 à 100 cas réels : photo du sommet + score prédit ce jour-là.
Recalibrer les poids en fonction des cas vrais vs faux.

---

## Les données sommets disponibles

Données issues d'OpenStreetMap (Overpass API) + enrichissement altitude Open-Meteo + entrées manuelles.

| Source | Nb entrées | Exemples |
|--------|-----------|---------|
| Pyrénées | ~6 566 | Vignemale (3298m), Pic du Midi de Bigorre (2877m) |
| Alpes Sud | ~4 185 | Mont Blanc (4807m), Aiguille du Midi (3842m) |
| Alpes Nord | ~2 479 | La Tournette (2351m), Col de la Croix-Fry (1477m) |
| Massif Central | ~765 | Puy de Sancy (1885m), Mont Aigoual (1567m) |
| Vosges | ~409 | Grand Ballon (1424m), Champ du Feu (1099m) |
| Viewpoints urbains | ~570 | La Bastille (476m), Fourvière (295m), Mont Saint-Clair (176m) |
| Autres (saddles, manuels…) | reste | — |

Pour régénérer depuis OpenStreetMap : `python scripts/generate_peaks.py`

Pour enrichir le champ `region` sans relancer Overpass : `python scripts/enrich_region.py`

---

## Prochaines étapes produit

1. **Story 6.2** — photo optionnelle + taux de précision par zone
2. **StoreKit 2** — abonnement réel (story 4.3)
3. **Déploiement VPS** — infra et monitoring de production
4. **Recalibration de l'algo** — après un volume suffisant de validations terrain
