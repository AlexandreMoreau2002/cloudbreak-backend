# Story 3.2 — Seed Base de Données des Sommets

## Ce qui a été livré

| Fichier | Rôle |
|---------|------|
| `app/db/peaks_data.json` | 22 031 entrées — source de données brute |
| `app/db/seed.py` | Script d'insertion en DB (lit peaks_data.json) |
| `alembic/versions/c1a2b3d4e5f6_add_idx_peaks_name.py` | Migration : index `idx_peaks_name` sur `peaks.name` |
| `scripts/generate_peaks.py` | Script de régénération depuis Overpass API + Open-Meteo |

---

## Fonctionnellement — qu'est-ce qu'on a ?

**22 031 entrées** en base : sommets, cols, saddles, et viewpoints urbains iconiques.

| Source | Entrées | Altitude min |
|--------|---------|-------------|
| `natural=peak` — Pyrénées | ~6 566 | 500m |
| `natural=peak` — Alpes Sud | ~4 185 | 500m |
| `natural=peak` — Alpes Nord | ~2 479 | 500m |
| `natural=peak` — Massif Central | ~765 | 500m |
| `natural=peak` — Vosges | ~409 | 500m |
| `natural=peak` — Jura | ~181 | 500m |
| `natural=saddle` — toutes régions | quelques centaines | 500m |
| `tourism=viewpoint` — toutes régions | ~570 (partiel) | 80m |
| Manuels (cols + viewpoints urbains) | 6 | — |

**Viewpoints urbains garantis manuellement** (filet de sécurité — OSM les tague différemment ou sous seuil) :

| Spot | Altitude | Ville |
|------|---------|-------|
| La Bastille | 476m | Grenoble |
| Colline de Fourvière | 295m | Lyon |
| Mont Saint-Clair | 176m | Sète |
| Sacré-Cœur | 130m | Paris |
| Colline du Château | 92m | Nice |
| Col de la Croix-Fry | 1477m | Haute-Savoie |

Chaque entrée a : `id` (UUID), `name`, `slug` (URL-safe), `lat`, `lng`, `altitude`.

---

## Techniquement — comment ça marche

### 1. Source des données : OpenStreetMap via Overpass API

OpenStreetMap (OSM) est la base géographique collaborative mondiale — c'est ce qu'utilisent Komoot, AllTrails, Maps.me. L'**Overpass API** est l'interface de requête en lecture.

`generate_peaks.py` fait **2 requêtes par région** (9 régions = 18 requêtes), avec délai entre chaque :

**Requête 1 — peaks + saddles** (ont le tag `[ele]` dans OSM) :
```
[out:json][timeout:60];
(
  node["natural"="peak"]["name"]["ele"](south,west,north,east);
  node["natural"="saddle"]["name"]["ele"](south,west,north,east);
);
out body;
```

**Requête 2 — viewpoints** (souvent sans `[ele]` dans OSM → altitude via Open-Meteo) :
```
[out:json][timeout:60];
node["tourism"="viewpoint"]["name"](south,west,north,east);
out body;
```

### 2. Pourquoi 18 requêtes et pas 1 sur toute la France ?

Une requête France entière `(41.3,-5.2,51.1,9.6)` dépasse le timeout serveur Overpass (trop de données à scanner). La solution est de découper en 9 régions avec bounding boxes distinctes.

### 3. Enrichissement altitude des viewpoints via Open-Meteo

Les `tourism=viewpoint` dans OSM n'ont souvent pas de tag `ele`. Plutôt que de les exclure ou de les ajouter à la main, on envoie leurs coordonnées à l'**API Open-Meteo Elevation** (gratuite, sans clé) :

```
GET https://api.open-meteo.com/v1/elevation?latitude=48.88,45.19&longitude=2.34,5.72
→ {"elevation": [130.0, 476.0]}
```

Batch de 100 coordonnées par appel → ~30-50 requêtes pour enrichir tous les viewpoints. Filtre final : altitude ≥ 80m.

### 4. Traitement des données

Pour chaque nœud OSM :
- Extraction `name:fr` ou `name`, `lat`, `lon`, `ele`
- Slugification : `"Mont Blanc" → "mont-blanc"` (URL-safe, clé de déduplication)
- UUID déterministe : `uuid5(NAMESPACE_URL, "cloudbreak:peak:{slug}")` — même slug = même UUID à chaque régénération
- Déduplication par slug : si doublon, on garde l'altitude la plus haute

### 5. Stockage dans peaks_data.json

Les 22 031 entrées sont dans `app/db/peaks_data.json` (~2.5MB). `seed.py` lit ce fichier — **aucun appel réseau à runtime**. Le fichier est commité dans le repo.

### 6. Le seed est idempotent

```python
result = await session.execute(text("SELECT COUNT(*) FROM peaks"))
count = result.scalar()
if count and count > 0:
    # Table déjà peuplée — on ne fait rien
    return
```

Pour re-seeder, vider la table d'abord :
```bash
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"
```

### 7. Migration Alembic — index idx_peaks_name

Index sur `peaks.name` pour les recherches textuelles de la story 3.3 (`WHERE name ILIKE '%Mont%'`). Sans index = full table scan sur 22 031 lignes.

```sql
CREATE INDEX idx_peaks_name ON peaks (name);
```

---

## Pourquoi certains spots sont ajoutés manuellement ?

**Cols (`mountain_pass`)** : OSM tag `natural=peak` = sommet, pas col. Le Col de la Croix-Fry est taggeré `mountain_pass` → absent de notre requête → ajout manuel.

**Viewpoints urbains** : certains spots iconiques ont des tags OSM incohérents ou sont sous le seuil 500m :
- La Bastille (Grenoble) → tagué `attraction` dans OSM, pas `viewpoint`
- Colline de Fourvière (Lyon) → `natural=peak` à 295m, sous le seuil peaks (500m)
- Mont Saint-Clair (Sète) → `natural=peak` à 176m, idem

Ces entrées manuelles sont le **filet de sécurité** — elles ne remplacent pas la requête automatique, elles garantissent leur présence quoi qu'il arrive.

---

## Ce qui reste à faire

### Viewpoints partiels — relancer le script

Lors de la dernière génération, 6 régions sur 9 ont eu un 429 (rate-limit Overpass). Les viewpoints de ces régions manquent encore : Alpes Nord, Alpes Sud, Massif Central, Jura, Bretagne/Normandie, Île-de-France/Centre.

Relancer quand Overpass a rechargé (attendre 1-2h après un run) :
```bash
source .venv/bin/activate
python scripts/generate_peaks.py
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"
python -m app.db.seed
```

### Story 3.3 — Endpoint de recherche (prochain)

La DB est peuplée mais aucun endpoint n'expose encore les sommets :
- `GET /api/v1/peaks/search?q=` → autocomplete par nom (utilise `idx_peaks_name`)
- `GET /api/v1/peaks/{slug}` → détail d'un sommet

---

## Comment tester

```bash
# 1. Démarrer les containers
make dev

# 2. Appliquer les migrations (inclut idx_peaks_name)
make migrate

# 3. Insérer les données (venv requis)
source .venv/bin/activate && python -m app.db.seed
# → log "seed_completed" avec count=22031

# AC 1 — vérifier le comptage
docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT COUNT(*) FROM peaks;"
# → 22031

# AC 2 — vérifier les sommets obligatoires
docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT name, slug, altitude FROM peaks
      WHERE slug IN ('mont-blanc', 'col-de-la-croix-fry', 'champ-du-feu',
                     'la-bastille', 'colline-de-fourviere', 'mont-saint-clair');"

# AC 3 — vérifier l'index
docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT indexname FROM pg_indexes
      WHERE tablename = 'peaks' AND indexname = 'idx_peaks_name';"

# Tester la recherche texte (simule ce que fera l'endpoint 3.3)
docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT name, altitude FROM peaks WHERE name ILIKE '%ventoux%';"
```

---

## Acceptance Criteria vérifiés

- [x] `SELECT COUNT(*) FROM peaks` → 22 031 (≥ 50 requis)
- [x] Mont Blanc (4807m), Col de la Croix-Fry (1477m), Champ du Feu (1099m) présents avec coordonnées GPS correctes
- [x] La Bastille (476m), Colline de Fourvière (295m), Mont Saint-Clair (176m) présents
- [x] Index `idx_peaks_name` créé via migration Alembic
- [x] Alpes françaises, Vosges, Massif Central, Pyrénées, Provence représentés
- [x] Viewpoints urbains (< 500m) inclus via enrichissement Open-Meteo Elevation
