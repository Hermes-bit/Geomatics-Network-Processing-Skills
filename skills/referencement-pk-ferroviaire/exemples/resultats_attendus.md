# Résultats attendus sur le jeu d'exemple

Ligne fictive 830000, voie V1 (schéma `ferro_exemple`), de 10+000 à 20+213.2, avec un saut de PK `15+400 = 15+650`.

```
psql -d ma_base -f exemples/donnees_exemple.sql
psql -d ma_base -f scripts/referencement_pk.sql
psql -d ma_base -f exemples/lancer_exemple.sql
```

## Ce qui est testé
- L'axe est en deux morceaux, le second à l'envers : il doit être fusionné et orienté de 10+000 vers 20+213.
- La ligne 831000 est dans la même table : elle doit être ignorée.
- Le kilomètre 15 ne mesure que 750 m : 400 m de 15+000 à 15+400, puis 350 m de 15+650 à 16+000.

## PK -> coordonnées (`pk_a_convertir.csv`)

| id | PK | décalage | X L93 | Y L93 | avertissement attendu |
|---|---|---|---|---|---|
| E01 | 11+250 | 0 | 801236.70 | 6500185.51 | aucun |
| E02 | 14+600 | -4,5 m (droite) | 804488.05 | 6499966.05 | aucun |
| E03 | 15+500 | 0 | vide | vide | PK inexistant : dans la lacune 15+400 = 15+650 |
| E04 | 17+080 | +3 m (gauche) | 806607.83 | 6500351.13 | aucun |
| E05 | 21+000 | 0 | vide | vide | PK hors de la ligne (10+000 à 20+213.2) |

## Coordonnées -> PK (`points_a_localiser.csv`)

| id | PK attendu | distance à l'axe | décalage | avertissement attendu |
|---|---|---|---|---|
| P01 | 12+499.8 | 0 m | 0 | aucun |
| P02 | 15+400 | 6 m | +6 (gauche) | au droit du saut de PK 15+400 = 15+650 |
| P03 | 15+800 | 3 m | -3 (droite) | aucun |
| P04 | 18+201 | 35 m | +35 | point à 35 m de l'axe : rattachement douteux |
| P05 | 19+948.8 | 2 m | +2 | aucun |

Les écarts de quelques décimètres (P01, P05) viennent des bornes, relevées volontairement avec ±1,5 m d'imprécision : c'est le comportement normal d'un calage sur bornes.

## Événements linéaires (`evenements_lineaires.csv`)

| id | de | à | longueur terrain | avertissement attendu |
|---|---|---|---|---|
| L01 | 12+200 | 13+500 | 1 298.9 m | aucun |
| L02 | 15+100 | 16+300 | 950.4 m (au lieu de 1 200) | contient la lacune 15+400 = 15+650 |

## Version QGIS

L'algorithme `qgis/referencement_pk_ferroviaire.py`, lancé sur `ligne_exemple.gpkg` (couches `axes`, `bornes_pk`, `sauts_pk`) avec les trois CSV ci-dessus, doit donner les mêmes coordonnées, PK, longueurs et avertissements. `python3 outils/tester_qgis.py` le vérifie automatiquement.
