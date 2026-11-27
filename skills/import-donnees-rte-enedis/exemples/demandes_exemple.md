# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple chargé dans PostGIS (schéma `elec_brut`) :

1. « Importe les fichiers RTE et Enedis de `elec_brut` en Lambert 93 et fais-moi le bilan par niveau de tension. »
2. « Contrôle la topologie du réseau importé. » (réponse attendue : une quasi-connexion de 0,6 m qui isole un câble HTA)
3. « Quelles lignes sont hors tension ou sans tension ? »
4. « Prépare ces réseaux pour une pré-analyse DT-DICT. »

Sur vos propres données :

- « Télécharge les lignes HTA et BT d'Enedis et les lignes RTE du Rhône, et charge-les dans ma base pour QGIS. »
- « Fais un contrôle de topologie du réseau HTA open data de ma commune et dis-moi ce qui ressemble à une vraie erreur. »
- « Calcule la longueur de réseau aérien et souterrain par commune à partir des données Agence ORE. »
