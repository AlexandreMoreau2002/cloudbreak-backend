# Peaks — Suivi de génération

Historique des runs `scripts/generate_peaks.py` et état de la DB par région.

---

## État actuel en DB

_Mis à jour : 2026-03-22 — **23 782 entrées** (run 3)_

| Région | Peaks/saddles | Viewpoints | Total estimé | Spots clés |
|--------|--------------|------------|--------------|------------|
| Alpes Nord | 3 705 | ~100 | ~3 800 | Mont Blanc ✅ |
| Alpes Sud | 6 085 | ~150 | ~6 200 | — |
| Vosges | 689 | ~80 | ~770 | Grand Ballon ✅, Champ du Feu ✅ |
| Massif Central | 1 487 | ~80 | ~1 550 | Puy de Dôme ✅ (volcano) |
| Jura | 319 | ~120 | ~430 | — |
| Pyrénées | 9 982 | ~180 | ~10 100 | — |
| Provence/Côte | 2 956 | ~150 | ~3 000 | Mont Ventoux ✅ |
| Bretagne/Normandie | **0** ⚠️ | 68 | 68 | Roc'h Trévezel ✅ (viewpoint), Ménez-Hom ✅ |
| IDF/Centre | **0** ⚠️ | 92 | 92 | viewpoints divers |
| Manuels | — | — | 8 | La Bastille ✅, Fourvière ✅, Mont Saint-Clair ✅, Montmartre ✅, Sacré-Cœur ✅, Colline du Château ✅, Col de la Croix-Fry ✅ |

**Note Bretagne/IDF :** les 0 peaks/saddles sont normaux — aucun sommet `natural=peak` au-dessus de 500m dans ces régions (Roc'h Trévezel = 369m). Ces spots sont capturés via le tag `tourism=viewpoint` enrichi Open-Meteo. **Fix prévu : baisser MIN_ALT_PEAK à 300m (run 4).**

---

## Runs historiques

### Run 3 — 2026-03-22 ✅ SUCCÈS

**Durée : ~1h30** (délais retry Overpass inclus — sans retry ça aurait duré ~20 min mais raté)
**Résultat final : 23 781 entrées** (record — +2 200 vs run 1)

**Objectif :** régénération complète propre après corrections.

**Corrections apportées avant ce run :**
- Ajout `natural=volcano` dans la requête Overpass → capte Puy de Dôme, Chaîne des Puys
- Retry exponentiel Overpass 429/504 : 60s → 120s → 240s
- Retry timeout réseau : 30s → 60s → 120s
- Timeout query Overpass : 60s → 90s
- Délai entre peaks et viewpoints : 5s → 15s
- Délai entre régions : 7s → 20s
- Viewpoints urbains ajoutés dans MANUAL_ENTRIES (filet de sécurité)

**Résultats par région :**

| Région | Peaks/Saddles | Viewpoints bruts | Retries |
|--------|---------------|-----------------|---------|
| Alpes Nord | 3 705 | 465 | 2× 504 |
| Alpes Sud | 6 085 | 452 | 1× 429 + 1× 504 |
| Vosges | 689 | 250 | 1× 429 |
| Massif Central | 1 487 (471 volcans) | 241 | 1× 504 viewpoints |
| Jura | 319 | 352 | 1× 504 viewpoints |
| Pyrénées | 9 982 (2 volcans) | 517 | — |
| Provence/Côte | 2 956 (1 volcano) | 456 | — |
| Bretagne/Normandie | **0** ❌ | 374 | 1× 504 peaks (épuisé) |
| IDF/Centre | **0** ❌ | 148 | 2× 504 peaks + 2× 504 viewpoints |

**Total final : 23 781 entrées** — 2 799 viewpoints enrichis / 3 255 bruts.

**Spots clés vérifiés :** mont-blanc ✅ puy-de-dome ✅ col-de-la-croix-fry ✅ champ-du-feu ✅ la-bastille ✅ colline-de-fourviere ✅ mont-saint-clair ✅ colline-du-chateau ✅ — sacre-coeur ❌ (ajouté en MANUAL_ENTRIES pour le prochain run)

---

### Run 2 — 2026-03-22 (raté — rate-limit)

Résultat : **15 429 entrées** — fichier discardé, DB inchangée.

Cause : script relancé trop tôt après run 1, quota Open-Meteo épuisé. Overpass 429/504 non gérés → régions entières skippées.

---

### Run 1 — 2026-03-21 (seed initial)

Résultat : **~21 597 entrées** en DB (dont viewpoints partiels).

Problèmes détectés après :
- `natural=volcano` absent → Puy de Dôme manquant
- Viewpoints partiels (rate-limit Open-Meteo sur certaines régions)
- Vosges et Bretagne absentes ou quasi-vides

---

## Procédure de reseed après génération

```bash
# 1. Vérifier le fichier généré
pytest tests/test_peaks_data.py -v   # doit passer tous les tests

# 2. Vider et reseeder
cd backend
docker compose -f docker-compose.dev.yml exec db \
  psql -U postgres -d cloudbreak -c "DELETE FROM user_favorites; DELETE FROM peaks;"
source .venv/bin/activate && python -m app.db.seed

# 3. Vérifier en DB
docker compose -f docker-compose.dev.yml exec db \
  psql -U postgres -d cloudbreak -c "SELECT COUNT(*) FROM peaks;"
```

---

## Améliorations futures

- [ ] **Run 4 — baisser MIN_ALT_PEAK 500m → 300m** pour capturer les vrais natural=peak bretons (Roc'h Trévezel, Ménez-Hom…) et les petits sommets IDF/Centre avec les métadonnées OSM correctes. Dataset estimé : ~30 000+ entrées. Durée : ~1h30.
- [ ] **Écriture dans un fichier temporaire** — le script doit écrire dans `peaks_data_new.json` au lieu d'écraser `peaks_data.json` directement. Workflow cible :
  1. `generate_peaks.py` → `peaks_data_new.json`
  2. Script de comparaison : count total, diff par région, spots clés présents/absents
  3. Validation manuelle → `mv peaks_data_new.json peaks_data.json`
  4. `pytest tests/test_peaks_data.py` → reseed
- [ ] Résolution spatiale : les bboxes actuelles se chevauchent → vérifier les zones de recouvrement (Alpes Nord/Alpes Sud, Massif Central/Provence)
- [ ] Bretagne/Normandie et IDF/Centre : 0 peaks/saddles OSM sur 2 runs consécutifs — ces régions ont peu de sommets taggés, ajouter des entrées manuelles pour les spots clés (Signal de Toarcé, Mont des Avaloirs, Butte de Montpinçon…)
- [ ] Ajouter tag `natural=ridge` pour les crêtes remarquables
- [ ] Passer à l'API Overpass turbo pour des quotas plus généreux
- [ ] Recommandation par proximité géo (story 3.4+) — nécessite lat/lng fiables pour tous les spots
