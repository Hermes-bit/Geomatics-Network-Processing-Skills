---
name: analyse-bilan-electrique
description: Contrôle et analyse un bilan électrique ou une courbe de charge au pas de 15 ou 30 minutes (bilan électrique demi-heure Enedis, données ODRÉ, export de télérelève) : pas manquants, doublons, changements d'heure, valeurs vides, équilibre injection / soutirage / pertes / consommation, puis énergies journalières, pointes et creux, part de production locale et des EnR, taux de pertes, sensibilité à la température, avec un rapport HTML. À utiliser pour vérifier, nettoyer, résumer ou exploiter des séries de puissance ou de consommation électrique.
---

# Analyse d'un bilan électrique au pas fin

Ce skill vérifie la qualité d'une série temporelle de puissances électriques et en tire des indicateurs fiables. Un script testé est fourni : `scripts/analyser_bilan.py` (Python 3.8 ou plus, bibliothèque standard uniquement, aucune installation).

## Règle d'or
- **Ne jamais modifier le fichier source.** Les résultats vont dans un dossier de sortie.
- **Ne jamais combler un trou sans le dire.** Une journée manquante rend les énergies journalières et les moyennes fausses : la signaler avant tout indicateur, et ne pas interpoler sauf demande explicite (en annonçant la méthode).
- **Annoncer l'unité.** Les jeux ouverts mélangent W, kW et MW, et puissance (W) et énergie (Wh). Le script devine l'unité d'après l'ordre de grandeur et le dit : la confirmer avec la documentation du jeu.

## Avant de commencer : informations à obtenir
1. Le fichier et sa source (Enedis, ODRÉ, export métier), et si les valeurs sont des **puissances moyennes** sur le pas (cas du bilan Enedis) ou des **énergies** par pas.
2. L'unité si elle est connue (`--unite W|kW|MW`), sinon le script la suppose.
3. La question posée : contrôle qualité seul, chiffres clés d'une période, comparaison de jours, lien avec la température.

## Ce qu'il faut savoir sur ces données
- **Changement d'heure** : un jour civil compte 92 pas de 15 min au passage à l'heure d'été (fin mars) et 100 au passage à l'heure d'hiver (fin octobre), au lieu de 96 (46, 50, 48 au pas de 30 min). Une horodate sans décalage horaire (`+01:00`) est ambiguë ces jours-là : la signaler. Le script travaille en UTC et rapporte en heure légale.
- **Bilan Enedis** : injection depuis RTE + production raccordée au réseau de distribution = soutirage vers RTE + soutirage vers d'autres gestionnaires + pertes + consommation. L'égalité est exacte dans les fichiers publiés ; un écart trahit une ligne corrompue ou une colonne mal lue.
- **Publication en J+4** : les dernières valeurs sont provisoires et peuvent être révisées. Le dire si l'analyse porte sur les derniers jours.
- **Colonnes à zéro** : une colonne nulle sur toute la période (par exemple `temperature_normale_lissee`) est le plus souvent une donnée non renseignée, pas une vraie valeur.
- **Énergie** = somme des puissances × durée du pas (0,25 h au pas de 15 min).
- **Sensibilité à la température** : elle demande au moins deux semaines de jours complets et plusieurs degrés d'écart ; sur quelques jours, l'effet semaine / week-end domine. Le script la calcule mais la déclare non exploitable en dessous de ces seuils.

## Étapes
1. Lancer : `python3 scripts/analyser_bilan.py bilan.csv --sortie resultats/` (séparateur `,` ou `;` et virgule décimale détectés).
2. Lire `resultats/controles.csv` : gravité `majeure` (pas manquants d'au moins une heure, doublons, bilan déséquilibré, horodates sans fuseau), `mineure` (trou court, valeur vide, valeur négative, sous-totaux incohérents, jour incomplet, colonne nulle), `info` (unité supposée, bilan équilibré, sensibilité à la température).
3. Lire `resultats/indicateurs_journaliers.csv` : énergies (MWh) de consommation, production, photovoltaïque, éolien, pertes et injection RTE ; pointe et creux de consommation (MW) avec l'heure ; part de production locale ; taux de pertes ; température moyenne. Un jour `non` (incomplet) ou `absent` ne doit pas entrer dans une moyenne ni une comparaison.
4. Ouvrir `resultats/rapport.html` (un seul fichier, sans dépendance) : courbes avec les trous en rouge, contrôles, tableau journalier. C'est le document à partager.

## Sortie
Dans la réponse : la période et le pas réellement couverts, les anomalies majeures en premier (avec leurs dates), puis 3 à 5 chiffres clés calculés **sur les jours complets seulement**, l'unité supposée et les limites (données provisoires, jours exclus, sensibilité à la température non exploitable). Joindre le rapport HTML.

## Lien avec les autres skills
Ces séries n'ont pas de géométrie : elles ne servent ni au contrôle de topologie ni aux PK. Elles complètent `import-donnees-rte-enedis` (cartographie des lignes et postes publiée sur les mêmes portails) pour relier un territoire, son réseau et ses flux.

## Exemple
`exemples/` contient :
- `bilan_enedis_reel_2026-11.csv` : un vrai bilan électrique demi-heure Enedis (pas de 15 min, du 14 au 22/11/2026, données ouvertes Enedis), où il manque toute la journée du 17/11 ;
- `bilan_fictif_changement_heure.csv` : trois jours fictifs autour du passage à l'heure d'hiver, au format `;` avec virgule décimale, avec une heure manquante, un doublon, une valeur vide et un pas déséquilibré ;
- `resultats_attendus.md`, `demandes_exemple.md`, `rapport_bilan_reel.html` (le rapport produit sur les données réelles) et `test_analyse_bilan.py` (test automatique).
