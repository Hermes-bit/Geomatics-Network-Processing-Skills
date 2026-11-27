# Résultats attendus sur le jeu d'exemple

Chantier fictif en trois polygones (schéma `dtdict_exemple`), neuf ouvrages, en Lambert 93.

```
psql -d ma_base -f exemples/donnees_exemple.sql
psql -d ma_base -f scripts/proximite_dt_dict.sql
psql -d ma_base -f exemples/lancer_exemple.sql
psql -d ma_base -f exemples/verifier_resultats.sql   # test automatique
```

## Contrôle de l'emprise

| Contrôle | Résultat | Conforme |
|---|---|---|
| géométrie valide | oui | oui |
| surface totale | 0,50 ha (maximum 20 ha) | oui |
| étendue | 422 m (maximum 20 km) | oui |
| écart entre polygones | 240 m (maximum 50 m) | **non** : le massif de candélabre doit faire l'objet d'une autre déclaration |

## Ouvrages

| id | Exploitant | Catégorie | Ce qui est placé | Situation attendue | Alerte attendue |
|---|---|---|---|---|---|
| 1 | Enedis | électricité HTA souterrain, classe B | traverse la tranchée | dans_emprise | investigations complémentaires |
| 9 | Syndicat intercommunal | autre, classe C | dans la fosse | dans_emprise | sensibilité à vérifier, classe C |
| 4 | Enedis | électricité BT aérien | à 2,5 m | fuseau_aerien | aucune |
| 2 | GRDF | gaz, classe A flexible | à 0,4 m | zone_incertitude (0,5 m) | aucune |
| 8 | Chaleur Urbaine | chaleur, classe B | à 1 m | zone_incertitude (1,5 m) | investigations complémentaires |
| 3 | Orange | télécom, classe vide | à 3 m | proximite | classe inconnue traitée comme C |
| 5 | RTE | électricité 63 kV aérien | à 4,5 m | proximite | ligne HTB : distances de sécurité ; **pas** d'exemption des 3 m |
| 7 | Métropole | assainissement, classe B | à 5 m | proximite | aucune |
| 6 | Régie des eaux | eau | à 20 m | **non retenu** | |

## Exploitants concernés

| Exploitant | Sensible | Situation la plus proche | IC à prévoir |
|---|---|---|---|
| Enedis | oui | dans_emprise | oui |
| GRDF | oui | zone_incertitude | non |
| Chaleur Urbaine | oui | zone_incertitude | oui |
| RTE | oui | proximite | non |
| Orange | non | proximite | non |
| Métropole | non | proximite | non |
| Syndicat intercommunal | à vérifier | dans_emprise | non |

Sept exploitants, la Régie des eaux n'en fait pas partie.
