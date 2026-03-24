# Cloudbreak — Audit produit

_Dernière mise à jour : 2026-03-24_

---

## C'est quoi Cloudbreak

Une app iOS qui répond à une seule question :
**"Est-ce que je vais voir une mer de nuage depuis ce sommet, à cette heure ?"**

L'utilisateur cherche un sommet, choisit une date et une heure, et reçoit une probabilité (0-100%) avec un verdict (`high` / `medium` / `low`).

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
| 22 397 entrées en base (sommets, cols, viewpoints) | ✅ Seedés — toute la France |
| Index idx_peaks_name | ✅ Migration Alembic |
| Script génération Overpass API + Open-Meteo elevation | ✅ scripts/generate_peaks.py |
| Migrations DB | ✅ Alembic |
| Tests — 92 tests, 100% coverage | ✅ |
| CI pipeline | ✅ GitHub Actions |
| Domain layer (`app/domain/`) — logique métier pure (zero I/O) | ✅ Refactorisé |

| Recherche sommets (`GET /api/v1/peaks/search` + `GET /api/v1/peaks/{slug}`) | ✅ ILIKE, limit 20 |
| Favoris (`POST/DELETE/GET /api/v1/user/favorites`) | ✅ Avec peak info jointe |

### Ce qui n'existe pas encore

- Gestion des abonnements / freemium / quota Redis
- Endpoint validations terrain (`POST /api/v1/validations`)
- Notifications push
- Déploiement VPS (infra prod)

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

### Règle absolue (hard gate)

Si la base des nuages est **au-dessus** du sommet → **0%, sans calcul**.

Exemple : sommet à 1720m, nuages qui commencent à 2500m → l'observateur est sous les nuages → mer de nuage impossible → 0%.

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

## Les 22 397 entrées disponibles

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

---

## Prochaines étapes produit

1. **Story 3-5** — détail conditions météo + fenêtre temporelle + stabilité (mobile)
2. **Freemium** — quota 1 consultation/jour pour les non-abonnés (epic 4)
3. **Validations terrain** — les utilisateurs confirment ou infirment le score avec une photo
4. **Recalibration de l'algo** — après 50+ validations terrain
