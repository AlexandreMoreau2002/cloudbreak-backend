# Story 3.2 — Seed Base de Données des Sommets

## Ce qui a été fait

| Fichier | Rôle |
|---------|------|
| `app/db/seed.py` | 64 sommets français/alpins — Alpes, Vosges, Massif Central, Provence |
| `alembic/versions/c1a2b3d4e5f6_add_idx_peaks_name.py` | Migration : index `idx_peaks_name` sur `peaks.name` |
| `scripts/generate_peaks.py` | Script de (re)génération des sommets via Overpass API (OSM) |

## Comment ça fonctionne

### Seed (`app/db/seed.py`)

- Vérifie d'abord si la table est vide (idempotent — ne ré-insère pas si déjà peuplée)
- Insère 64 sommets couvrant : Alpes françaises (hauts sommets + massifs moyens), Vosges, Massif Central, Provence, Pyrénées, Bretagne
- Données issues d'OpenStreetMap (Overpass API) + compléments manuels
- UUIDs déterministes (`uuid5` basé sur le slug) pour les sommets ajoutés manuellement

### Migration Alembic (`c1a2b3d4e5f6`)

- Chaîne après `b90b920dc145` (init peaks)
- Crée `idx_peaks_name` (non-unique) sur `peaks.name` pour accélérer les recherches textuelles (`LIKE`, `ILIKE`)

### Script de génération (`scripts/generate_peaks.py`)

- Interroge Overpass API avec des bounding boxes par massif (Alpes, Vosges, Massif Central, Jura, Pyrénées)
- Filtre les pics avec `natural=peak`, `name` et `ele` (altitude)
- Génère le bloc `PEAKS = [...]` prêt à coller dans `seed.py`
- Usage : `python scripts/generate_peaks.py > /tmp/peaks.py` (requiert connexion internet)

## Comment tester

### Vérifier le compte (AC 1)

```bash
# Lancer la migration puis le seed
make migrate
make seed

# Vérifier en DB
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"
# → 64 (> 50 requis)
```

### Vérifier les sommets obligatoires (AC 2)

```bash
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak -c "
SELECT name, slug, lat, lng, altitude
FROM peaks
WHERE slug IN ('mont-blanc', 'col-de-la-croix-fry', 'champ-du-feu');
"
```

Résultat attendu :
```
      name          |         slug          |   lat    |   lng   | altitude
--------------------+-----------------------+----------+---------+----------
 Mont Blanc         | mont-blanc            | 45.8327  | 6.8652  |     4807
 Col de la Croix-Fry| col-de-la-croix-fry  | 45.9075  | 6.5015  |     1477
 Champ du Feu       | champ-du-feu          | 48.4000  | 7.2242  |     1099
```

### Vérifier l'index (AC 3)

```bash
docker exec cloudbreak-db psql -U cloudbreak -d cloudbreak -c "
SELECT indexname FROM pg_indexes
WHERE tablename = 'peaks' AND indexname = 'idx_peaks_name';
"
# → idx_peaks_name
```

## Acceptance Criteria vérifiés

- [x] `SELECT COUNT(*) FROM peaks` → 64 (≥ 50 requis)
- [x] Mont Blanc, Col de la Croix-Fry, Champ du Feu existent avec coordonnées GPS et altitudes correctes
- [x] Index `idx_peaks_name` créé via migration Alembic
- [x] Alpes françaises, Vosges, Massif Central représentés
