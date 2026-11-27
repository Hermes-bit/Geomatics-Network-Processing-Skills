# Demandes types

1. « Voici l'emprise de mon chantier (emprise.gpkg) et nos couches de réseaux dans PostGIS. Fais-moi l'analyse d'impact complète : exploitants à consulter, risques, carte et PDF. »
2. « On doit traverser la ligne 830000 par fonçage vers le PK 15+675. Qu'est-ce que le chantier touche, et entre quels PK faut-il prévoir la protection ferroviaire ? »
3. « Prépare le dossier d'impact de ce chantier pour la réunion de préparation : registre des risques classés, liste des exploitants avec contacts, parcelles à occuper et propriétaires. »
4. « J'ai lancé le LiDAR sur les lignes du secteur (troncons_vegetation.geojson). Ajoute la végétation à l'analyse d'impact et dis-moi ce qu'il faut élaguer avant les travaux. »
5. « Je n'ai que QGIS : lance l'analyse d'impact sur le GeoPackage du chantier et sors-moi la carte HTML à envoyer au conducteur de travaux. »

Avec les données d'exemple : charger `donnees_exemple.sql` (et la voie du skill PK), puis demander par exemple « Analyse l'impact du chantier du schéma impact_exemple sur la ligne 830000 ». Comparer avec `resultats_attendus.md`.
