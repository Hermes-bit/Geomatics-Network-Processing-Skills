# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple chargé dans PostGIS (schéma `ferro_exemple`) :

1. « Sur la ligne 830000, donne-moi les coordonnées Lambert 93 du PK 11+250 et du PK 17+080 décalé de 3 m à gauche. Les bornes sont dans `ferro_exemple.bornes_pk`, les sauts dans `ferro_exemple.sauts_pk`. »
2. « Convertis le fichier `exemples/pk_a_convertir.csv` en coordonnées et sors-moi un CSV. »
3. « À quel PK se trouvent les points de `exemples/points_a_localiser.csv` ? Signale ceux qui sont trop loin de la voie. »
4. « Quelle est la longueur réelle du chantier entre 15+100 et 16+300 ? » (réponse attendue : environ 950 m à cause du saut de PK)
5. « Le PK 15+500 existe-t-il sur cette ligne ? »

Sur vos propres données :

- « J'ai une couche des lignes SNCF Réseau en GeoJSON (WGS84) et un tableau Excel d'ouvrages d'art avec code ligne et PK. Place-les sur la carte. »
- « Je n'ai pas de bornes, seulement l'axe de la ligne 570000 qui commence au PK 0+000. Calcule les PK de mes passages à niveau. »
- « Transforme ces limitations de vitesse (de PK à PK) en tronçons de ligne pour QGIS. »
