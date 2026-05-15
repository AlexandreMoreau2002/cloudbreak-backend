# Algorithme de score — mer de nuage

Ce fichier documente la **structure et les invariants** de l'algorithme. Les valeurs numériques des constantes ne sont pas dupliquées ici — elles vivent dans `app/domain/score_components.py` et `app/services/weather_providers/open_meteo.py`. Ce qu'on maintient ici, c'est le *pourquoi* et la *logique physique* — ce qui doit rester vrai même si les chiffres changent.

---

## 1. Variables météo en entrée

### Source : Open-Meteo `/v1/forecast`

| Variable | Champ Open-Meteo | Unité | Rôle dans l'algo |
|---|---|---|---|
| `cloud_cover_low` | `cloud_cover_low` | % | Hard gate 2 + composante indirecte |
| `humidity` | `relative_humidity_2m` | % | Composante humidité |
| `wind_speed` | `wind_speed_10m` | km/h | Composante vent |
| `temperature_2m` | `temperature_2m` | °C | Contexte / présentation |
| `pressure` | `surface_pressure` | hPa | Composante pression |
| `temperature_925hpa` | `temperature_925hPa` | °C | Inversion thermique (niveau bas ~800m) |
| `temperature_850hpa` | `temperature_850hPa` | °C | Inversion thermique (niveau haut ~1500m) |

### Niveaux de pression — pour le calcul de la base des nuages

Quatre tranches atmosphériques, chacune fournit : température, humidité relative, altitude géopotentielle (MSL), dew point spread.

| Niveau | Altitude approximative | Usage |
|---|---|---|
| 925 hPa | ~800m | Plancher de détection — nuages très bas |
| 850 hPa | ~1500m | Couche principale mer de nuage + inversion |
| 800 hPa | ~1950m | Nuages moyens-bas |
| 700 hPa | ~3000m | Plafond de détection |

> L'altitude géopotentielle varie chaque jour — Open-Meteo la fournit pour chaque niveau à chaque requête. Ne pas utiliser les altitudes approx. ci-dessus dans le code.

### Variable dérivée : `cloud_base`

La base des nuages n'est **pas fournie directement** par Open-Meteo. Elle est calculée par la méthode Skew-T : on monte de bas en haut dans les niveaux de pression et on retourne l'altitude du premier niveau saturé.

Critère de saturation : `relative_humidity >= seuil ET dew_point_spread < seuil`

Constantes dans `open_meteo.py` : `CLOUD_RH_THRESHOLD`, `CLOUD_DEWPOINT_SPREAD_MAX`.

Si aucun niveau saturé n'est trouvé → `cloud_base = 5000m` (ciel dégagé).

---

## 2. Conditions bloquantes (hard gates)

Ces deux conditions sont vérifiées **avant tout calcul**. Si l'une est vraie → `score = 0`, `verdict = "none"`, la suite est court-circuitée.

### Gate 1 — Base des nuages au-dessus du sommet

```
cloud_base >= peak_altitude  →  BLOQUÉ
```

**Logique physique** : si les nuages sont au niveau du sommet ou au-dessus, l'observateur est dans les nuages ou les voit de dessous. Pas de mer de nuage possible — la mer de nuage se voit *depuis le haut*, elle suppose que les nuages sont *en dessous*.

### Gate 2 — Couverture nuageuse basse insuffisante

```
cloud_cover_low < seuil  →  BLOQUÉ
```

**Logique physique** : même si le cloud_base est bien placé, un ciel trop dégagé ne forme pas un tapis continu. Il faut un minimum de couverture pour qu'il y ait quelque chose à voir.

Constante dans `score_components.py` : `CLOUD_COVER_LOW_MIN_GATE`.

---

## 3. Composantes du score

Si les deux gates passent, le score est calculé comme une somme pondérée de cinq composantes. Chaque composante retourne une valeur `0.0 → 1.0` via interpolation linéaire entre deux seuils.

### Structure invariante

```
score = (
    WEIGHT_CLOUD_BASE  × cloud_base_score
  + WEIGHT_INVERSION   × inversion_score
  + WEIGHT_HUMIDITY    × humidity_score
  + WEIGHT_WIND        × wind_score
  + WEIGHT_PRESSURE    × pressure_score
) × 100
```

Les poids sont dans `score_components.py` et somment à 1.0.

### Interprétation physique de chaque composante

**cloud_base_score** — *Où sont les nuages par rapport au sommet ?*
La variable la plus importante. Plus les nuages sont loin en dessous du sommet, mieux c'est — l'observateur a une vue dégagée sur un tapis continu. Deux seuils : marge optimale (score max) et marge maximale au-dessus (score min).

**inversion_score** — *Y a-t-il un couvercle thermique ?*
Calculée à partir de `T(850hPa) − T(925hPa)`. Un delta positif signifie qu'il fait plus chaud en altitude qu'au sol — une inversion thermique. Ce phénomène agit comme un couvercle : il bloque la convection et maintient les nuages bas en place. Sans inversion, les nuages montent et envahissent le sommet.

**humidity_score** — *Les nuages sont-ils bien alimentés ?*
Humidité relative à 2m. Un air humide au sol signifie que les nuages bas sont alimentés en continu et ne vont pas se dissiper rapidement.

**wind_score** — *Le vent laisse-t-il les nuages stables ?*
Un vent fort déstructure le tapis de nuages et l'empêche de former une surface homogène. Score inversé : plus le vent est faible, meilleur est le score.

**pressure_score** — *Les conditions générales sont-elles stables ?*
Une haute pression (anticyclone) est associée à des conditions stables, peu de perturbations, ciel dégagé au-dessus. Corrélation avec la persistance de la mer de nuage.

---

## 4. Caps de score (plafonnement conditionnel)

Après le calcul du score brut, des caps sont appliqués séquentiellement pour éviter les faux positifs. Chaque cap s'applique sur le résultat du précédent.

### Principe

Un cap fonctionne ainsi : `score = min(plafond_fixe, round(score × facteur_réducteur))`

Les constantes (plafonds et facteurs) sont dans `score_components.py`.

### Les quatre caps et leur justification physique

**Cap 1 — Pas d'inversion thermique**
Condition : `T(850hPa) ≤ T(925hPa)`
Sans inversion, rien ne maintient les nuages en place. Ils vont monter et noyer le sommet. Un score élevé sans inversion est trompeur — ce cap ramène le score sous le seuil "medium".

**Cap 2 — Base des nuages trop proche du sommet**
Condition : `cloud_base > peak_altitude − marge_min`
Si les nuages sont à moins de X mètres sous le sommet, le risque de brouillard au sommet est élevé. La mer de nuage "parfaite" suppose une marge confortable.

**Cap 3 — Couverture nuageuse basse insuffisante pour un "high"**
Condition : `cloud_cover_low < seuil_high`
Le gate 2 a laissé passer (couverture > seuil_bas), mais si la couverture reste en dessous d'un seuil plus élevé, le tapis est trop fragmenté pour justifier un verdict "high".

**Cap 4 — Vent fort**
Condition : `wind_speed >= seuil_fort`
Au-delà d'un certain vent, la mer de nuage ne tient pas en forme compacte. Ce cap plafonne sous le seuil "medium".

---

## 5. Verdict final

Après application des caps :

| Verdict | Condition |
|---|---|
| `"none"` | Hard gate 1 ou 2 déclenché (score = 0) |
| `"high"` | score ≥ seuil_high ET inversion détectée ET cloud_base ≤ peak − marge ET cloud_cover_low ≥ seuil_high_cover |
| `"medium"` | score ≥ seuil_medium (mais pas toutes les conditions "high") |
| `"low"` | score < seuil_medium (gates passés, conditions médiocres) |

**Pourquoi "high" a ses propres conditions en plus du score ?**
Les caps peuvent maintenir un score élevé même si une condition clé manque. Le verdict "high" est délibérément strict : il signifie "mer de nuage probable ET spectaculaire". Mieux vaut une surprise agréable qu'une déception.

Les seuils numériques sont dans `score_components.py` : `HIGH_MIN_SCORE`, `MEDIUM_MIN_SCORE`, `HIGH_MIN_LOW_CLOUD_COVER`, `HIGH_MIN_MARGIN_BELOW_SUMMIT`.

---

## 6. Ce qui est stable vs ce qui peut évoluer

### Stable — ne pas changer sans discussion

- La structure à deux étages (gates → score pondéré)
- Les cinq composantes et leur interprétation physique
- La logique des quatre caps et leur justification
- La structure du verdict final (none / low / medium / high)
- La méthode Skew-T pour le calcul de cloud_base
- Les quatre niveaux de pression utilisés (925 / 850 / 800 / 700 hPa)

### Souple — peut évoluer par recalibration

- Les valeurs numériques de tous les seuils et poids → `score_components.py`
- Les seuils de saturation Skew-T → `open_meteo.py`
- Le TTL du cache météo → `weather.py`
- Le provider météo (Open-Meteo peut être remplacé par Météo-France sans changer l'algo)

### À venir (non modélisé en v1)

- **Zones** : un massif ou un versant observable depuis plusieurs points — aujourd'hui l'algo travaille sur un point unique (lat/lng)
- **Validations terrain** : la table `terrain_validations` existe mais n'alimente pas encore l'algo
- **Recalibration par zone** : ajuster les seuils par massif à partir des validations réelles
- **Variables supplémentaires** : `cloud_cover_mid`, visibilité, gradient de rosée en surface — à évaluer si elles améliorent la précision
