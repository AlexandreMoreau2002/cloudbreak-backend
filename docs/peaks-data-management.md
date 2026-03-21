# Gestion des données sommets (peaks)

## Ce qu'on a aujourd'hui

**21 574 entrées** couvrant toute la France : sommets, cols, viewpoints urbains iconiques, issus d'OpenStreetMap + entrées manuelles.

| Source | Entrées | Altitude min |
|--------|---------|-------------|
| `natural=peak` — Pyrénées | ~6 566 | 500m |
| `natural=peak` — Alpes Sud | ~4 185 | 500m |
| `natural=peak` — Alpes Nord | ~2 479 | 500m |
| `natural=peak` — Massif Central | ~765 | 500m |
| `natural=peak` — Vosges | ~409 | 500m |
| `natural=peak` — Jura | ~181 | 500m |
| `natural=saddle` — France | ~quelques centaines | 500m |
| `tourism=viewpoint` — France | ~quelques centaines | 100m |
| Manuels (cols + viewpoints urbains) | 6 | — |

**Viewpoints urbains manuels** (tagués différemment ou sous seuil dans OSM) :

| Spot | Altitude | Ville | Raison d'ajout manuel |
|------|---------|-------|----------------------|
| La Bastille | 476m | Grenoble | tagué `attraction` dans OSM, pas `viewpoint` |
| Colline de Fourvière | 295m | Lyon | `natural=peak` mais sous seuil 500m |
| Mont Saint-Clair | 176m | Sète | `natural=peak` mais sous seuil 500m |
| Sacré-Cœur | 130m | Paris | aucun tag `ele` dans OSM |
| Colline du Château | 92m | Nice | aucun tag `ele` dans OSM |
| Col de la Croix-Fry | 1477m | Haute-Savoie | `mountain_pass` pas `natural=peak` |

**Stratégie viewpoints automatique** : `generate_peaks.py` requête tous les `tourism=viewpoint["name"]` sans filtre `[ele]`, puis enrichit leur altitude via l'**API Open-Meteo Elevation** (gratuite, batch 100 coords). Filtre final : altitude ≥ 80m. Les spots manuels ci-dessus sont la garantie filet de sécurité si Overpass/Open-Meteo ne les capturent pas.

---

## Architecture des données

```
scripts/generate_peaks.py    ← outil de régénération (appelle Overpass API)
         ↓ génère
app/db/peaks_data.json       ← source de vérité commitée dans le repo (2MB)
         ↓ lu par
app/db/seed.py               ← insère en DB au déploiement (idempotent)
         ↓ insère dans
PostgreSQL → table peaks     ← ce que l'app interroge à runtime
```

**Le JSON est la source de vérité.** L'app ne contacte jamais Overpass API — elle lit uniquement la DB.

---

## Étendre à une nouvelle région

### Étape 1 — Identifier la bounding box

Outil recommandé : [bboxfinder.com](http://bboxfinder.com) — dessine un rectangle, copie les coordonnées.

Format Overpass : `(sud, ouest, nord, est)` — attention, **longitude en deuxième**, pas en premier.

Exemples pour futures extensions :

| Zone | Sud | Ouest | Nord | Est | Alt min |
|------|-----|-------|------|-----|---------|
| Alpes suisses | 45.8 | 6.0 | 47.8 | 10.5 | 1000m |
| Alpes autrichiennes | 46.4 | 9.5 | 48.0 | 17.2 | 1000m |
| Dolomites (Italie) | 45.8 | 10.5 | 47.0 | 13.0 | 1000m |
| Cantabrie (Espagne) | 42.8 | -5.5 | 43.6 | -1.5 | 800m |
| Écosse (Highlands) | 56.0 | -6.5 | 58.5 | -2.0 | 600m |
| Atlas (Maroc) | 30.0 | -9.5 | 33.5 | -4.0 | 1500m |

### Étape 2 — Ajouter la région dans generate_peaks.py

```python
# Dans la liste REGIONS de scripts/generate_peaks.py
{
    "name": "Alpes suisses",
    "bbox": (45.8, 6.0, 47.8, 10.5),
    "min_alt": 1000,
},
```

### Étape 3 — Régénérer peaks_data.json

```bash
cd backend
source .venv/bin/activate
python scripts/generate_peaks.py > /tmp/new_peaks_data.json 2>/tmp/generate_log.txt

# Vérifier le résultat
cat /tmp/generate_log.txt
# Remplacer le fichier source
cp /tmp/new_peaks_data.json app/db/peaks_data.json
```

### Étape 4 — Re-seeder en dev

```bash
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "DELETE FROM peaks;"
make seed
docker exec cloudbreak-db psql -U postgres -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"
```

### Étape 5 — Commiter

```bash
git add app/db/peaks_data.json
git commit -m "feat(peaks): ajout Alpes suisses (~XXXX sommets)"
```

---

## Ajouter un sommet ou col manuellement

Pour les **cols** et lieux spécifiques qui n'ont pas le tag `natural=peak` dans OSM (ex : Col de la Croix-Fry, Col du Galibier...) :

### 1. Trouver les coordonnées GPS précises

Utiliser [openstreetmap.org](https://www.openstreetmap.org) : chercher le col/sommet, clic droit → "Afficher l'adresse" pour obtenir lat/lng.

### 2. Générer l'UUID déterministe

```python
import uuid
slug = "col-du-galibier"  # adapter
uid = uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{slug}")
print(uid)  # → toujours le même pour ce slug
```

### 3. Ajouter dans generate_peaks.py

À la fin de `main()`, avant la sauvegarde JSON, dans la liste `MANUAL_OVERRIDES` :

```python
MANUAL_OVERRIDES = [
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "cloudbreak:peak:col-de-la-croix-fry")),
        "name": "Col de la Croix-Fry",
        "slug": "col-de-la-croix-fry",
        "lat": 45.9075,
        "lng": 6.5015,
        "altitude": 1477,
    },
    # Ajouter ici les nouveaux cols/sommets manuels
]
```

Ces entrées sont fusionnées avec les données OSM — un slug déjà présent dans OSM sera ignoré (OSM a la priorité).

---

## Limites connues et points d'attention

### Qualité OSM variable

- **Grands sommets** (Mont Blanc, Vignemale, Grand Ballon) : données fiables, noms officiels
- **Petits sommets locaux** : altitudes parfois approximatives (arrondies à 10m près), noms parfois en langue régionale (occitan, basque, alsacien)
- **Doublons géographiques** : même sommet, deux nœuds OSM avec noms légèrement différents — le slug ne dédoublonne que si le nom est identique

### Ce que le filtre `natural=peak` exclut

| Exclusion | Raison | Contournement |
|-----------|--------|---------------|
| Cols (`mountain_pass`) | Tag OSM différent | Ajout manuel |
| Sommets < 500m | Filtre altitude | Baisser `min_alt` |
| Points de vue (`viewpoint`) | Tag OSM différent | Requête séparée |
| Refuges / cabanes | Pas un sommet | Non pertinent |

### Rate-limit Overpass API

Overpass API est un service public gratuit — il impose un rate-limit.
- **1 requête à la fois** — ne pas paralléliser
- **12 secondes minimum entre chaque requête** — respecté dans `generate_peaks.py`
- **Timeout 60s par requête** — les bounding boxes trop grandes échouent (ex : France entière = timeout)
- **Quota quotidien** : ~10 000 requêtes/jour par IP — pas un problème pour un usage ponctuel

Si une requête échoue avec 429 ou timeout : attendre 60 secondes et relancer uniquement cette région.

---

## Roadmap données peaks

| Priorité | Action | Impact |
|----------|--------|--------|
| MVP | France entière ✅ | 13 898 sommets |
| Post-MVP | Score popularité (nb vues, altitude) | Meilleur tri dans la recherche |
| V2 | Alpes suisses + italiennes | +8 000 sommets |
| V2 | Pyrénées espagnoles | +3 000 sommets |
| V2 | Inclusion cols `mountain_pass` | Spots iconiques manquants |
| V3 | Synchronisation OSM automatique (cron) | Données toujours à jour |
