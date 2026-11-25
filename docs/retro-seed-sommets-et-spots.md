# Session 3.2 — Log des actions

Ce fichier trace tout ce qui a été fait pendant la session story 3.2 (peaks data).
Les commandes ont été exécutées par Claude — pas par l'utilisateur.

---

## Fichiers créés

| Fichier | Action |
|---------|--------|
| `app/db/peaks_data.json` | Créé (2MB+, 22 031 entrées) |
| `app/db/seed.py` | Modifié (print → logger, imports, typage) |
| `scripts/generate_peaks.py` | Créé |
| `alembic/versions/c1a2b3d4e5f6_add_idx_peaks_name.py` | Créé |
| `docs/story-3-2-seed-sommets.md` | Créé |
| `docs/peaks-data-management.md` | Créé |
| `README.md` | Modifié |

---

## Commandes exécutées

### Génération des données

```bash
# Première génération — Alpes Nord seulement (les autres avaient timeout)
source .venv/bin/activate && python scripts/generate_peaks.py

# Régénération complète après extension viewpoints (9 régions × 3 types)
source .venv/bin/activate && python scripts/generate_peaks.py
# → 21 569 entrées dans app/db/peaks_data.json

# Ajout manuel des 5 viewpoints urbains directement dans le JSON (Python inline)
python3 -c "
import json, uuid
from pathlib import Path
peaks = json.loads(Path('app/db/peaks_data.json').read_text())
# ... ajout La Bastille, Fourvière, Mont Saint-Clair, Sacré-Cœur, Colline du Château
"
# → 21 574 entrées

# Script incrémental viewpoints OSM sans [ele] + Open-Meteo elevation
python3 /tmp/enrich_viewpoints.py
# → 457 nouveaux viewpoints ajoutés (partiel — 6 régions rate-limitées Overpass)
# → 22 031 entrées finales
```

### Base de données

```bash
# Vérifier l'état initial
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"

# Vider la table pour re-seeder (fait plusieurs fois au fil des régénérations)
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"

# Seeder (toujours depuis le venv — make seed ne fonctionnait pas sans venv activé)
source .venv/bin/activate && python -m app.db.seed

# Vérifications après seed
docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT name, altitude FROM peaks WHERE slug IN ('mont-blanc','la-bastille','colline-de-fourviere','mont-saint-clair');"

docker exec cloudbreak-db psql -U postgres -d cloudbreak \
  -c "SELECT indexname FROM pg_indexes WHERE tablename='peaks' AND indexname='idx_peaks_name';"
```

### Qualité code

```bash
source .venv/bin/activate

ruff check scripts/generate_peaks.py   # lint
ruff format scripts/generate_peaks.py  # formatage
mypy scripts/generate_peaks.py         # typage
make validate                          # ruff + mypy + pytest (sur app/)
```

### Génération des UUIDs (pour les entrées manuelles)

```bash
python3 -c "
import uuid
slugs = ['la-bastille','colline-de-fourviere','mont-saint-clair','sacre-coeur','colline-du-chateau']
for slug in slugs:
    print(uuid.uuid5(uuid.NAMESPACE_URL, f'cloudbreak:peak:{slug}'))
"
```

---

## Requêtes Overpass lancées

9 régions × 2-3 passages = ~20 requêtes au total sur https://overpass-api.de

| Région | bbox | Résultat |
|--------|------|---------|
| Alpes Nord | (45.5, 5.5, 46.5, 7.5) | ~2 479 peaks + 465 viewpoints bruts |
| Alpes Sud | (44.0, 5.5, 45.5, 7.5) | ~4 185 peaks |
| Vosges | (47.7, 6.6, 48.8, 7.4) | ~409 peaks + 250 viewpoints bruts |
| Massif Central | (44.5, 2.3, 46.2, 4.5) | ~765 peaks |
| Jura | (46.0, 5.4, 47.5, 6.5) | ~181 peaks |
| Pyrénées | (42.4, -2.0, 43.5, 3.3) | ~6 566 peaks + 517 viewpoints bruts |
| Provence/Côte | (43.0, 4.5, 44.5, 7.5) | peaks + 456 viewpoints bruts |
| Bretagne/Normandie | (47.0, -5.5, 50.0, -0.5) | peaks |
| Île-de-France/Centre | (47.5, 1.0, 49.5, 4.0) | peaks |

Les viewpoints de 6 régions sur 9 ont eu un 429 (rate-limit) lors du dernier passage.

---

## Appels Open-Meteo Elevation lancés

URL : `https://api.open-meteo.com/v1/elevation`

- ~11 batches de 100 coordonnées (1 080 viewpoints dédupliqués)
- Batches 1-6 : OK → 568 viewpoints enrichis ≥ 80m
- Batches 7-11 : 429 Too Many Requests → ces viewpoints perdus (altitude = 0, filtrés)

---

## Ce qu'il reste à faire

Relancer le script complet quand Overpass a rechargé son quota (attendre 1-2h) :

```bash
cd backend
source .venv/bin/activate
python scripts/generate_peaks.py
# Durée : ~5 min (18 requêtes Overpass + Open-Meteo batches)

# Puis re-seeder
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"
python -m app.db.seed
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"
```

Ensuite : **story 3.3** — `GET /api/v1/peaks/search?q=` + `GET /api/v1/peaks/{slug}`

---

## Problème rencontré — run partiel qui écrase les données

### Ce qui s'est passé

Lors du dernier relancement de `generate_peaks.py`, plusieurs régions ont eu des 504/429 (Overpass rate-limit + Open-Meteo rate-limit). Le script écrit le résultat **en entier et en une seule fois** à la fin — il a donc produit un `peaks_data.json` de seulement ~16 700 entrées au lieu des 22 000+ précédentes, écrasant le fichier commité.

### Comment on a récupéré

```bash
# 1. Récupérer le fichier peaks_data.json du dernier commit (avant l'écrasement)
git show HEAD:app/db/peaks_data.json > /tmp/peaks_previous.json

# 2. Fusionner : garder l'ancien + ajouter les nouveaux slugs du run partiel
python3 -c "
import json
from pathlib import Path

prev = json.loads(open('/tmp/peaks_previous.json').read())
curr = json.loads(Path('app/db/peaks_data.json').read_text())

prev_slugs = {p['slug'] for p in prev}
new_entries = [p for p in curr if p['slug'] not in prev_slugs]

merged = prev + new_entries
merged.sort(key=lambda p: -p.get('altitude', 0))
Path('app/db/peaks_data.json').write_text(json.dumps(merged, ensure_ascii=False, indent=2))
print(f'Fusionné : {len(merged)} entrées ({len(new_entries)} nouvelles)')
"

# 3. Re-seeder
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"
source .venv/bin/activate && python -m app.db.seed

# 4. Vérifier
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"
```

### À retenir pour les prochains runs

- **Commiter avant de relancer le script** — si le run plante, `git show HEAD:app/db/peaks_data.json` permet de récupérer la version précédente
- **Attendre 1-2h entre deux runs** — Overpass et Open-Meteo ont des quotas qui se rechargent
- **Le script écrase tout** — il ne fait pas de merge automatique. Si des régions échouent, le fichier produit est incomplet. Toujours fusionner avec la version précédente via le snippet ci-dessus si le count final est inférieur au précédent
- **Vérifier le count avant de commiter** : si `len(peaks)` < nombre précédent dans le log → ne pas commiter, fusionner d'abord
