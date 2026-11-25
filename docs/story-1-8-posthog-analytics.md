# Story 1.8 — PostHog backend

## Résultat

Le backend FastAPI transmet désormais les événements métier autorisés vers PostHog quand
`POSTHOG_API_KEY` et `POSTHOG_HOST` sont présents. L'intégration conserve tous les appelants
existants derrière `track()` et reste limitée au projet dev/TestFlight.

## Comportement sans clé

L'initialisation est un no-op si la clé ou l'hôte est vide. L'API démarre normalement, le client
n'est pas créé et `track()` n'effectue aucun appel réseau. L'arrêt ne tente un flush que si un
client a réellement été initialisé.

## Données et confidentialité

- Une liste blanche accepte uniquement les événements métier connus et leurs propriétés prévues.
  Un événement inconnu ou une propriété libre est ignoré sans casser la route métier.
- Le `distinct_id` est l'identifiant pseudonyme déjà fourni par l'appelant. Aucun e-mail, jeton,
  message d'erreur, corps HTTP, localisation précise ni donnée arbitraire n'est ajouté.
- Le SDK désactive l'enrichissement GeoIP, les traces, l'autocapture d'exceptions et l'évaluation
  locale. Session Replay, logs, feature flags et profils de personne ne font pas partie de cette
  intégration.
- `auth_submitted` reste absent de l'activation mobile tant que son `error_code` n'est pas un enum
  stable ; il n'est donc pas envoyé par cette story.

## Validation effectuée

- Les tests ciblés couvrent le no-op sans configuration, une capture autorisée, le rejet des
  événements/propriétés non autorisés et l'arrêt protégé.
- `make validate` a réussi avec 712 tests au moment de l'intégration.
- La revue sécurité a confirmé le filtrage des données et l'absence de chemins de capture
  automatique.

## Déploiement dev requis

Renseigner `POSTHOG_API_KEY` et `POSTHOG_HOST` uniquement dans l'environnement Dokploy **dev**,
relire les variables sans les recopier dans les logs, puis redéployer et valider avec la build
mobile dev/TestFlight. Ne pas envoyer de trafic public vers ce projet : un projet et une clé
PostHog de production séparés sont requis avant activation publique.
