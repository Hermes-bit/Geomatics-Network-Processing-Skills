# Résultats attendus sur le chantier d'exemple

Chantier fictif : raccordement HTA en tranchée avec traversée de la ligne 830000 (voie V1) par fonçage, au droit du saut de PK 15+400 = 15+650 du jeu d'exemple du skill `referencement-pk-ferroviaire`. Paramètres par défaut (marge DT-DICT 5 m, voies 20 m, débattement des engins 5 m, végétation et riverains 20 m).

Test automatique : `PGDATABASE=ma_base ./exemples/chainer_exemple.sh` (PostGIS, avec la végétation si `numpy` et `laspy` sont installés) et `python3 outils/tester_qgis.py` (QGIS, avec le dossier PDF et la carte HTML).

## Synthèse
- Niveau global **critique** : 5 risques critiques, 4 majeurs, 7 à traiter, 4 pour information (20 en tout).
- Emprise : 1 341,2 m² en 6 polygones, **non conforme pour une seule déclaration** : la zone de stockage est à 60,7 m de la tranchée (maximum 50 m).
- 5 exploitants, dont 4 de réseaux sensibles. La conduite d'eau à 54 m n'est pas retenue.

## Registre des risques
| N° | Niveau | Thème | Objet | Pourquoi |
|---|---|---|---|---|
| 1 | critique | ferroviaire | Ligne 830000, PK 15+264.4 à 15+699.1 (à 0,5 m près) | le fonçage coupe la voie entre 15+674 et 15+676 ; 184,9 m de voie à moins de 20 m, mais 435 m d'écart de PK : la section contient la lacune 15+400 = 15+650 |
| 2 | critique | voisinage électrique | Ouvrage 4, RTE 63 kV aérien | surplombe la tranchée, distance de sécurité 5 m |
| 3 | critique | voisinage électrique | Ouvrage 5, caténaire 25 kV | surplombe le fonçage, distance de sécurité 3 m |
| 4 | critique | réseaux | Ouvrage 1, Enedis HTA souterrain classe B | dans l'emprise, investigations complémentaires |
| 5 | critique | réseaux | Ouvrage 6, câble de signalisation SNCF classe C | dans l'emprise, investigations complémentaires |
| 6 | majeur | déclaration | Emprise : écart entre polygones | 60,7 m |
| 7 | majeur | réseaux | Ouvrage 2, gaz GRDF classe A | à 0,30 m, dans la zone d'incertitude de 0,5 m (PE, flexible) |
| 8 | majeur | végétation | Voie V1, tronçon 6 gauche | arbre de 14 m à 7 m de l'axe : risque de chute |
| 9 | majeur | végétation | Ligne RTE, tronçon 3 droite | arbre de 7 m à 2 m de l'axe : hauteur excessive |
| 10 | à traiter | réseaux | Ouvrage 3, télécom sans classe | dans l'emprise, non sensible, traité comme C |
| 11 | à traiter | végétation | Voie V1, tronçon 7 droite | arbre de 22 m à 22 m : à surveiller |
| 12 à 16 | à traiter | foncier | Parcelles AB 0101 (SNCF RESEAU, 104 m²), AB 0102 (400 m², zone de stockage), AB 0103 (280 m²), AB 0104 (COMMUNE, 340 m²), AC 0202 (SCI DES SAULES, 216 m²) | parcelles occupées |
| 17, 18 | information | végétation | Voie V1, tronçon 9 gauche et droite | pas de LiDAR au-delà de s = 35 m |
| 19 | information | foncier | Parcelle AB 0105 | riveraine à 15 m |
| 20 | information | foncier | Parcelle AC 0203 | contact de 1,2 m² seulement : imprécision du cadastre |

Ne doivent **pas** apparaître : la conduite d'eau (ouvrage 7, à 54 m), les parcelles AB 0106 (44 m), AC 0201 (22 m) et AC 0204 (70 m).

## Exploitants
| Exploitant | Situation la plus proche | Investigations complémentaires | Niveau le plus grave |
|---|---|---|---|
| Enedis | dans l'emprise | oui | critique |
| RTE | dans l'emprise | non | critique |
| SNCF Réseau | dans l'emprise (caténaire, câble de signalisation) | oui | critique |
| GRDF | zone d'incertitude | non | majeur |
| Orange | dans l'emprise | non | à traiter |

## Végétation (vrai script du skill vegetation-lidar-hd sur le nuage fictif)
`generer_nuage_exemple.py` place trois arbres. Sur les 2 × 10 tronçons de la voie et les 2 × 9 tronçons de la ligne RTE, le skill végétation signale notamment : voie tronçon 6 gauche (14 m, `1_intervenir`), voie tronçon 7 droite (22 m, `2_surveiller`), RTE tronçon 3 droite (7 m, `1_intervenir`), et des tronçons `sans_donnees`. Seuls ceux à moins de 20 m de l'emprise entrent dans le registre. `troncons_vegetation_exemple.geojson` est ce résultat, pour tester la version QGIS sans `laspy`.

## Dossier
`dossier_exemple.pdf` (carte et synthèse, puis exploitants, registre des risques et parcelles) et `carte_exemple.html` (carte interactive, risques numérotés et cliquables) sont produits par l'algorithme QGIS sur ces données.
