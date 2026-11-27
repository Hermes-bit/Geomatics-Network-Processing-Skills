# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple chargé dans PostGIS (schéma `sncf_brut`) :

1. « Importe les données SNCF de `sncf_brut` en Lambert 93 et dis-moi ce qui cloche. »
2. « Y a-t-il des sauts de PK sur la ligne 999000 ? » (réponse attendue : 4+000 = 4+250)
3. « Prépare la ligne 999000 pour le référencement PK et donne-moi les coordonnées du PK 5+300. »
4. « Quels passages à niveau sont mal placés ou ont un PK illisible ? »

Sur vos propres données :

- « Télécharge les lignes, gares et passages à niveau de SNCF Réseau pour la région Auvergne-Rhône-Alpes et charge-les dans ma base `sig` pour QGIS. »
- « J'ai le GeoJSON des formes des lignes du RFN : prépare la ligne 830000 pour convertir mes PK en coordonnées. »
- « Fais-moi une couche des ouvrages d'art (passerelles, ponts-route, passages souterrains) de la ligne 570000 avec leur PK. »
