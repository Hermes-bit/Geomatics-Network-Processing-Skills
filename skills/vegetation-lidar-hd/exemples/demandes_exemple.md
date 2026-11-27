# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple (`python3 exemples/generer_nuage_exemple.py /tmp/essai`) :

1. « Analyse la végétation autour de `lignes_exemple.geojson` avec `nuage_exemple.las` et dis-moi où il faut élaguer en priorité. »
2. « Quels arbres peuvent tomber sur la ligne L1 ? »
3. « Refais l'analyse de la voie V1 avec une emprise de 6 m et une hauteur maximale de 1 m. »
4. « Pourquoi la fin de la voie V1 n'a pas de résultat ? » (réponse attendue : pas de données LiDAR au-delà de 210 m)

Sur vos propres données :

- « J'ai téléchargé les dalles LiDAR HD autour de mon départ HTA (GeoJSON des lignes aériennes joint). Prépare un programme d'élagage par tronçon de 50 m. »
- « Repère les arbres qui pourraient tomber sur la ligne 830000 entre Lyon et Ambérieu, à partir du LiDAR HD et des voies SNCF Réseau. »
- « Fais une première carte des hauteurs de végétation sous les lignes RTE de ma commune avec le MNH LiDAR HD dans QGIS. »
