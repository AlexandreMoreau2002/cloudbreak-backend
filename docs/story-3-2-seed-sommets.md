# Story 3.2 — Seed Base de Données des Sommets

## Ce qui a été livré

| Fichier | Rôle |
|---------|------|
| `app/db/peaks_data.json` | 13 898 sommets — source de données brute |
| `app/db/seed.py` | Script d'insertion en DB (lit peaks_data.json) |
| `alembic/versions/c1a2b3d4e5f6_add_idx_peaks_name.py` | Migration : index `idx_peaks_name` sur `peaks.name` |
| `scripts/generate_peaks.py` | Script de régénération des données depuis Overpass API |

---

## Fonctionnellement — qu'est-ce qu'on a ?

**13 898 sommets** insérables en base, couvrant toute la France montagneuse :

| Massif | Sommets | Altitude min |
|--------|---------|-------------|
| Pyrénées | ~6 566 | 800m |
| Alpes Sud (44-45.5°N) | ~4 185 | 800m |
| Alpes Nord (45.5-46.5°N) | ~2 479 | 800m |
| Massif Central | ~765 | 600m |
| Vosges | ~409 | 600m |
| Jura | ~181 | 700m |
| Col de la Croix-Fry | 1 | manuel |

Chaque sommet a : `id` (UUID), `name`, `slug` (URL-safe), `lat`, `lng`, `altitude`.

---

## Techniquement — comment ça marche

### 1. Source des données : OpenStreetMap via Overpass API

OpenStreetMap (OSM) est la base géographique collaborative mondiale — c'est ce qu'utilisent Komoot, AllTrails, Maps.me. L'**Overpass API** est l'interface de requête en lecture.

La requête utilisée filtre les nœuds OSM avec :
- tag `natural=peak` → c'est un sommet géographique (pas un col, pas une ville)
- tag `name` → le sommet a un nom
- tag `ele` → l'altitude est renseignée

```
[out:json][timeout:60];
node["natural"="peak"]["name"]["ele"](south,west,north,east);
out body;
```

On lance cette requête **6 fois**, une par région (bounding box différente), avec 12 secondes de délai entre chaque pour respecter le rate-limit Overpass.

### 2. Pourquoi 6 requêtes et pas 1 sur toute la France ?

Une requête France entière `(41.3,-5.2,51.1,9.6)` retourne **0 résultats** — pas parce qu'il n'y a rien, mais parce qu'elle dépasse le timeout serveur de 90 secondes d'Overpass (trop de données à scanner). La solution est de découper en zones plus petites.

### 3. Traitement des données

Après chaque requête :
- Parsing du JSON Overpass → extraction `name`, `lat`, `lon`, `ele`
- Slugification du nom (`"Mont Blanc" → "mont-blanc"`) pour l'URL et comme clé de déduplication
- Génération d'un UUID déterministe : `uuid5(NAMESPACE_URL, "cloudbreak:peak:{slug}")` — le même slug produira toujours le même UUID, peu importe quand on regénère
- Déduplication : si deux nœuds OSM ont le même slug (ex : doublon de saisie), on garde celui avec l'altitude la plus haute

### 4. Stockage dans peaks_data.json

Les 13 898 sommets sont stockés dans `app/db/peaks_data.json` (2MB). `seed.py` lit ce fichier au moment du seed — il ne fait **pas** d'appel réseau. Le fichier est commité dans le repo.

Pourquoi un JSON séparé plutôt que dans `seed.py` ?
- Mettre 13 898 entrées dans un fichier `.py` ferait ~120 000 lignes illisibles
- Le JSON est lisible, versionnable, et peut être remplacé sans toucher au code
- `seed.py` reste simple et court (< 60 lignes)

### 5. Le seed est idempotent

```python
result = await session.execute(text("SELECT COUNT(*) FROM peaks"))
count = result.scalar()
if count and count > 0:
    # Table déjà peuplée — on ne fait rien
    return
```

On peut lancer `make seed` plusieurs fois, il n'y aura jamais de doublon.

### 6. Migration Alembic — index idx_peaks_name

La story exige un index sur `peaks.name` pour accélérer les recherches textuelles de la story 3.3 (`GET /api/v1/peaks/search?q=`). Sans index, une recherche `WHERE name ILIKE '%Mont%'` sur 13 898 lignes fait un full table scan.

```sql
CREATE INDEX idx_peaks_name ON peaks (name);
```

---

## Pourquoi Col de la Croix-Fry est ajouté manuellement ?

OSM tag `natural=peak` signifie littéralement **sommet** — le point le plus haut d'une montagne ou d'une crête. Un **col** (passage entre deux versants) est taggeré `mountain_pass` dans OSM, pas `natural=peak`.

**Col de la Croix-Fry** (1477m, Haute-Savoie) est un col de ski / randonnée — il n'est pas dans notre requête `natural=peak`. Mais c'est un spot mer de nuage iconique et l'AC de la story exige qu'il soit présent.

Il est ajouté manuellement avec des coordonnées vérifiées (45.9075°N, 6.5015°E) et un UUID uuid5 déterministe — exactement comme les 13 898 autres.

**Autres cas similaires qui pourraient manquer :** d'autres cols comme le Col de la Schlucht (Vosges), le Col du Galibier, etc. ne seront pas dans la base à moins d'être ajoutés manuellement ou qu'on change le filtre OSM pour inclure `mountain_pass`.

---

## Ce qui reste à faire

### Story 3.3 — Endpoint de recherche (prochain)

La DB est peuplée mais aucun endpoint n'expose encore les sommets :
- `GET /api/v1/peaks/search?q=` → autocomplete par nom (utilise `idx_peaks_name`)
- `GET /api/v1/peaks/{slug}` → détail d'un sommet

Sans ça, l'app mobile ne peut pas chercher un sommet.

### Qualité des données OSM — limite connue

OSM est collaboratif : la qualité des données dépend des contributeurs. Sur 13 898 sommets :
- Les grands sommets (Mont Blanc, Vignemale...) sont fiables
- Les petits sommets locaux peuvent avoir des altitudes approximatives ou des noms en langue régionale (occitan, basque, alsacien)
- Certains nœuds sont des doublons géographiques (même sommet, deux nœuds OSM légèrement décalés) — le slug les dédoublonne si le nom est identique, mais pas s'ils ont des noms légèrement différents

Pour le MVP, c'est largement suffisant. Une curation manuelle serait utile avant le lancement pour les 50 sommets les plus consultés.

### Évolution du filtre

Le filtre actuel `natural=peak` + `altitude >= 500-800m` exclut :
- Les cols (`mountain_pass`) → intéressants pour la mer de nuage
- Les sommets < 500m → peu pertinents mais existent (Roc'h Trévezel à 384m en Bretagne)

Ces exclusions sont intentionnelles pour le MVP.

---

## Comment tester

```bash
# 1. Démarrer les containers
make dev

# 2. Appliquer les migrations (inclut idx_peaks_name)
make migrate

# 3. Insérer les données
make seed
# → log "seed_completed" avec count=13898

# AC 1 — vérifier le comptage
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak \
  -c "SELECT COUNT(*) FROM peaks;"
# → 13898

# AC 2 — vérifier les sommets obligatoires
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak \
  -c "SELECT name, slug, lat, lng, altitude FROM peaks
      WHERE slug IN ('mont-blanc', 'col-de-la-croix-fry', 'champ-du-feu');"

# AC 3 — vérifier l'index
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak \
  -c "SELECT indexname FROM pg_indexes
      WHERE tablename = 'peaks' AND indexname = 'idx_peaks_name';"

# Tester la recherche texte (simule ce que fera l'endpoint 3.3)
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak \
  -c "SELECT name, altitude FROM peaks WHERE name ILIKE '%ventoux%';"
```

---

## Acceptance Criteria vérifiés

- [x] `SELECT COUNT(*) FROM peaks` → 13 898 (≥ 50 requis)
- [x] Mont Blanc (4807m), Col de la Croix-Fry (1477m), Champ du Feu (1099m) présents avec coordonnées GPS correctes
- [x] Index `idx_peaks_name` créé via migration Alembic
- [x] Alpes françaises, Vosges, Massif Central représentés
