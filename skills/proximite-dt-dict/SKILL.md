---
name: proximite-dt-dict
description: Repère les réseaux (électricité, gaz, télécom, eau, chaleur, voies ferrées…) proches d'une emprise de travaux et liste les exploitants à consulter pour une DT, une DICT ou une ATU, avec PostGIS. Tient compte des classes de précision A, B, C, des zones d'incertitude, du fuseau des réseaux aériens et signale les investigations complémentaires à prévoir. À utiliser pour toute demande de pré-analyse DT-DICT, de recherche des réseaux ou exploitants concernés par un chantier, ou de contrôle d'une emprise avant déclaration sur le guichet unique.
---

# Proximité DT-DICT : réseaux et exploitants concernés par un chantier

Ce skill croise une emprise de travaux avec des couches de réseaux et livre, pour chaque exploitant, ce qui le concerne et à quelle distance. Un script PostGIS testé est fourni : `scripts/proximite_dt_dict.sql`.

## Règle d'or
- **Ce n'est pas la déclaration officielle.** La liste des exploitants à consulter est celle que renvoie le guichet unique, le téléservice [reseaux-et-canalisations.ineris.fr](https://www.reseaux-et-canalisations.ineris.fr). Ses zones d'implantation ne sont pas publiées en données ouvertes. Le skill sert à préparer l'emprise, à contrôler la réponse du guichet unique et à repérer ce qui manque. Le dire dans chaque réponse.
- Ne jamais conclure qu'il n'y a « aucun réseau » : on ne voit que les couches fournies.
- Ne jamais modifier les données source : tout se fait dans le schéma de travail `dtdict`.

## Ce qu'il faut savoir (arrêté du 15 février 2012 modifié)
- **Classes de précision** (art. 1er) : A = incertitude maximale de 40 cm pour un ouvrage rigide, 50 cm pour un ouvrage flexible ; B = plus que A et au plus 1,5 m (1 m pour un branchement) ; C = plus de 1,5 m, ou l'exploitant ne sait pas localiser. Une classe inconnue se traite comme C.
- **Zone d'incertitude** : autour de la position théorique, la largeur de l'incertitude de la classe. L'art. 7-3 prévoit des précautions dans une bande de 1,5 m (1 m pour un branchement) quand les investigations complémentaires n'ont pas atteint la précision voulue.
- **Emprise** (art. 4) : polygones espacés de 50 m au plus, 20 ha au total au plus (2 ha pour des travaux urgents ou une déclaration conjointe), et pas plus de 20 km entre les deux points les plus éloignés. Au-delà, il faut plusieurs déclarations.
- **Réseaux aériens** (art. 2) : pour des travaux aériens sans permis de construire, pas de DT ni de DICT si l'emprise reste à plus de 3 m, en projection horizontale, d'une ligne électrique aérienne basse tension ou d'une ligne de traction ferroviaire. Cette exemption ne vaut pas pour les lignes HTA et HTB, où les distances de sécurité du code du travail s'appliquent.
- **Réseaux sensibles pour la sécurité** (art. R. 554-2 du code de l'environnement) : électricité, gaz, hydrocarbures, produits chimiques, chaleur, installations ferroviaires ou guidées notamment. Télécom, eau et assainissement sont non sensibles. La correspondance par défaut est dans la table `dtdict.categories` : la vérifier.
- **Investigations complémentaires** : quand un ouvrage sensible enterré n'est pas en classe A dans l'emprise, le responsable de projet doit en général faire des investigations complémentaires ou demander des mesures de localisation. Le script le signale, à confirmer avec les réponses des exploitants.

Ces règles sont résumées à partir de l'arrêté. Pour un usage réglementaire, vérifier la version en vigueur sur Légifrance.

## Avant de commencer : informations à obtenir
1. L'emprise : polygones (GeoPackage, shapefile, KML du guichet unique, DXF), leur SCR, et si les travaux sont urgents.
2. Les couches de réseaux disponibles et, pour chacune : exploitant, catégorie, mode de pose (souterrain, aérien, subaquatique), classe de précision, ouvrage rigide ou flexible, branchement, tension.
3. La marge de proximité à afficher au-delà de l'emprise. Par défaut 5 m : l'annoncer.
4. Les coordonnées des exploitants, si on veut une liste prête à envoyer.

Données ouvertes utiles quand l'utilisateur n'a pas les réseaux : lignes RTE (ODRÉ, opendata.reseaux-energies.fr), réseaux de distribution d'électricité (opendata.enedis.fr et opendata.agenceore.fr), voies ferrées (ressources.data.sncf.com). Elles ne remplacent pas les plans des exploitants : leur classe de précision est inconnue, donc C. Les skills `import-donnees-rte-enedis` et `import-donnees-sncf-reseau` de ce dépôt les préparent.

## Étapes

### 1. Préparer l'emprise
- Tout en **Lambert 93 (2154)** : le script s'arrête si ce n'est pas le cas. Reprojeter avec `ST_Transform`. Un KML ou un GeoJSON est en WGS84 (4326).
- Réparer avec `ST_MakeValid` et fusionner les polygones d'une même déclaration (`ST_Union`).
- Contrôler la surface, l'écart entre polygones et l'étendue. Signaler tout dépassement : il faut découper la déclaration.

### 2. Chercher les ouvrages
- Distance de chaque ouvrage à l'emprise : `ST_Distance` (index spatial et `ST_DWithin` pour ne pas tout parcourir).
- Incertitude selon la classe, puis situation, dans cet ordre :
  - `dans_emprise` : l'ouvrage coupe l'emprise ;
  - `fuseau_aerien` : ouvrage aérien à moins de 3 m en projection horizontale ;
  - `zone_incertitude` : la distance est inférieure à l'incertitude de la classe ;
  - `proximite` : plus loin, mais dans la marge choisie.
- Alertes : classe C ou inconnue, catégorie de sensibilité inconnue, investigations complémentaires à prévoir, ligne HTA ou HTB aérienne, exemption possible des 3 m.

### 3. Regrouper par exploitant
Une ligne par exploitant : catégories, réseau sensible ou non, nombre d'ouvrages, distance minimale, situation la plus proche, investigations complémentaires à prévoir, contact.

## Sortie
- `dtdict.controle_emprise` : contrôles de l'emprise avec `conforme`.
- `dtdict.ouvrages_concernes(id, exploitant, categorie, sensible, pose, classe, incertitude_m, tension_kv, distance_m, situation, alertes, geom)` : ouvrable dans QGIS, à styler par `situation`.
- `dtdict.exploitants_concernes` et la vue `dtdict.resume`.
- CSV `resultat_exploitants.csv` et `resultat_ouvrages.csv` (voir `exemples/lancer_exemple.sql`).

Dans la réponse :
1. Une phrase qui rappelle que la liste officielle vient du guichet unique.
2. Les contrôles de l'emprise non conformes.
3. Le tableau des exploitants, réseaux sensibles en premier.
4. Les alertes importantes : investigations complémentaires, classe C, lignes aériennes HTA ou HTB.
5. Les hypothèses : couches utilisées, marge, correspondance des catégories, classes manquantes.

## Utiliser le script fourni
1. Lire `scripts/proximite_dt_dict.sql`.
2. Adapter la section 0 : paramètres et vues `src_emprise`, `src_ouvrages`, `src_exploitants`. Mettre `NULL` pour un attribut absent (une classe `NULL` est traitée comme C).
3. Exécuter, lire `dtdict.controle_emprise` et `dtdict.exploitants_concernes`.
4. Exporter avec `exemples/lancer_exemple.sql`, ou dans QGIS (Couche > Ajouter une couche PostGIS).

## Dans QGIS sans PostGIS
*Tampon* sur l'emprise (marge choisie), *Extraire par localisation* sur chaque couche de réseau, puis *Joindre les attributs par localisation (résumé)* pour la distance. Le calcul des zones d'incertitude par classe se fait avec un tampon à distance variable (expression `CASE` sur la classe).

## Exemple
`exemples/` contient un chantier fictif en trois polygones et neuf ouvrages avec des pièges volontaires (`donnees_exemple.sql`), les résultats attendus (`resultats_attendus.md`), un test automatique (`verifier_resultats.sql`) et des demandes types (`demandes_exemple.md`).
