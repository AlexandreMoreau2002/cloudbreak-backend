# Decision Record — seuil minimal de `cloud_cover_low`

## Statut

Actif a partir du `2026-03-29`.

## Decision

Le projet retient les seuils produit suivants :

- `cloud_cover_low < 45%` -> aucun score mer de nuage n'est calcule
- `45% <= cloud_cover_low < 55%` -> score possible, mais verdict `high` interdit
- `cloud_cover_low >= 55%` -> verdict `high` a nouveau autorise si les autres composantes suivent

## Pourquoi ce choix

Le seuil precedent a `35%` etait trop permissif pour une app qui veut inspirer confiance.
Il laissait passer des situations avec "un peu" de nuages bas, mais pas une couche assez
franche pour produire une lecture produit credible.

Le passage a `45%` sert de garde-fou de fiabilite :

- on coupe plus tot les faux espoirs
- on evite les scores faibles affiches sur des ciels trop degages
- on preserve encore les cas limites interessants au-dessus du hard gate

Le seuil `55%` pour `high` force une couche basse plus nette avant d'afficher un scenario
franchement favorable.

## Nature du choix

Cette decision est **fondamentale** pour le projet parce qu'elle definit quand
l'application a le droit de "parler de scenario" plutot que de renvoyer un non.

Ce n'est pas une verite scientifique definitive.
C'est un arbitrage produit base sur la fiabilite percue avec la donnee actuellement
disponible : `cloud_cover_low`.

## Limite connue

`cloud_cover_low` n'est qu'un proxy local de couverture nuageuse basse.
Ce n'est pas une mesure complete de la qualite regionale d'une mer de nuage.

Autrement dit :

- le seuil actuel ameliore nettement l'honnetete produit
- mais il devra probablement evoluer quand on aura de meilleures donnees ou une validation
  empirique plus fine

## Evolution future attendue

Ce seuil pourra etre refine plus tard avec, par exemple :

- calibration sur observations terrain / retours utilisateurs
- distinction par massif ou type de topographie
- prise en compte de la continuite spatiale de la couche, pas seulement de sa presence locale
- meilleure lecture regionale de la couverture basse

Tant qu'on ne dispose pas de ce niveau de precision, `45% / 55%` est la base produit de
reference a conserver dans les discussions, tests et revues.
