# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple chargé dans PostGIS (schéma `reseau_exemple`) :

1. « Contrôle la topologie du réseau HTA dans `reseau_exemple.troncons` et `reseau_exemple.postes`. Le poste source est de type `poste_source`, les points d'ouverture sont dans `etat_exploitation = 'NO'`. »
2. « Quelles extrémités de câble sont à moins d'un mètre d'un autre tronçon sans y être raccordées ? »
3. « Est-ce que j'ai des boucles fermées sur mon réseau radial ? Donne-moi les tronçons concernés. »
4. « Le tronçon 13 croise le tronçon 2, est-ce une erreur ? » (réponse attendue : non, souterrain sous aérien, franchissement normal)
5. « Prépare-moi les requêtes pour corriger les anomalies majeures, mais ne les exécute pas. »

Sur vos propres données :

- « Vérifie la topologie de ma couche `public.lignes_bt` (colonnes `gid`, `the_geom`), tolérance 5 cm, et sors-moi une couche d'anomalies à ouvrir dans QGIS. »
- « J'ai exporté mon réseau ferré en GeoPackage depuis QGIS, il est en WGS84. Contrôle les connexions entre voies en tenant compte des ponts (colonne `niveau`). »
- « Mon graphe pgRouting donne des itinéraires bizarres, peux-tu trouver les coupures dans le réseau ? »
