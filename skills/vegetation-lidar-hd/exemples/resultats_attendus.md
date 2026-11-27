# Résultats attendus sur le jeu d'exemple

Nuage fictif généré par `generer_nuage_exemple.py` (LAS 1.4, classes LiDAR HD, Lambert 93, origine X0 = 900000, Y0 = 6500000).

```
python3 exemples/test_vegetation.py          # génère, analyse et compare (test automatique)
# ou à la main :
python3 exemples/generer_nuage_exemple.py /tmp/essai
python3 scripts/vegetation_lidar.py --lignes /tmp/essai/lignes_exemple.geojson --sortie /tmp/essai/resultats /tmp/essai/nuage_exemple.las
```

## La scène
- **L1** : ligne électrique aérienne de 200 m (8 tronçons de 25 m de chaque côté), règles par défaut (emprise 5 m, hauteur max 4 m).
- **V1** : voie ferrée de 250 m, 60 m plus au nord (10 tronçons de chaque côté), règles par défaut (emprise 4 m, hauteur max 1,5 m). Le LiDAR s'arrête à x = 210 m.

## Tronçons signalés

| Ligne | Tronçon | Côté | Ce qui est placé | Priorité attendue |
|---|---|---|---|---|
| L1 | 2 (25-50 m) | gauche | arbre de 12 m à 8 m de l'axe | 1_intervenir (risque de chute, marge -4,4 m) |
| L1 | 5 (100-125 m) | droite | arbuste de 5 m à 2 m de l'axe | 1_intervenir (hauteur excessive) |
| L1 | 8 (175-200 m) | droite | arbre de 10 m à 12 m | 2_surveiller (marge 1,7 m) |
| V1 | 3 (50-75 m) | gauche | végétation de 2 m à 3 m de la voie | 1_intervenir (hauteur excessive) |
| V1 | 6 (125-150 m) | gauche | arbre de 15 m à 10 m | 1_intervenir (risque de chute) |
| V1 | 10 (225-250 m) | gauche et droite | pas de LiDAR | sans_donnees, avec un avertissement |

Les 29 autres tronçons sont `3_rien_a_signaler`, dont celui de l'arbre de 10 m à 20 m de L1 (tronçon 7 gauche) : il ne peut pas atteindre la ligne.

Hauteur mesurée de l'arbre de 12 m : 12,0 m (± 0,2 m). `points_signales.geojson` contient des cellules des deux motifs pour chaque ligne.
