# -*- coding: utf-8 -*-
"""
Test automatique : génère le nuage d'exemple dans un dossier temporaire, lance l'analyse et
compare avec resultats_attendus.md. Code de sortie 0 si tout est conforme, 1 sinon.

Usage : python3 exemples/test_vegetation.py   (numpy et laspy requis)
"""

import csv
import json
import os
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "scripts"))
import generer_nuage_exemple  # noqa: E402
import vegetation_lidar  # noqa: E402

ATTENDU = {   # (ligne, tronçon, côté) -> priorité ; tout le reste doit être « 3_rien_a_signaler »
    ("L1", 2, "gauche"): "1_intervenir",   # arbre de 12 m à 8 m : chute
    ("L1", 5, "droite"): "1_intervenir",   # arbuste de 5 m sous la ligne
    ("L1", 8, "droite"): "2_surveiller",   # arbre de 10 m à 12 m
    ("V1", 3, "gauche"): "1_intervenir",   # végétation de 2 m à 3 m de la voie
    ("V1", 6, "gauche"): "1_intervenir",   # arbre de 15 m à 10 m : chute
    ("V1", 10, "gauche"): "sans_donnees",  # pas de LiDAR au-delà de x = 210
    ("V1", 10, "droite"): "sans_donnees",
}

erreurs = []
with tempfile.TemporaryDirectory() as tmp:
    generer_nuage_exemple.generer(tmp)
    sortie = os.path.join(tmp, "resultats")
    vegetation_lidar.principal(["--lignes", os.path.join(tmp, "lignes_exemple.geojson"),
                                "--sortie", sortie, os.path.join(tmp, "nuage_exemple.las")])
    with open(os.path.join(sortie, "troncons_vegetation.csv"), encoding="utf-8") as f:
        troncons = list(csv.DictReader(f))
    with open(os.path.join(sortie, "bilan.json"), encoding="utf-8") as f:
        bilan = json.load(f)
    with open(os.path.join(sortie, "points_signales.geojson"), encoding="utf-8") as f:
        points = json.load(f)["features"]

if len(troncons) != 36:
    erreurs.append(f"36 tronçons attendus (8 x 2 pour L1, 10 x 2 pour V1), {len(troncons)} obtenus")
for t in troncons:
    cle = (t["id_ligne"], int(t["troncon"]), t["cote"])
    attendu = ATTENDU.get(cle, "3_rien_a_signaler")
    if t["priorite"] != attendu:
        erreurs.append(f"{cle} : priorité {t['priorite']} au lieu de {attendu}")
haut = next(t for t in troncons if (t["id_ligne"], t["troncon"], t["cote"]) == ("L1", "2", "gauche"))
if abs(float(haut["hauteur_max_m"]) - 12.0) > 0.2:
    erreurs.append(f"hauteur de l'arbre de 12 m mesurée à {haut['hauteur_max_m']} m")
motifs = {(p["properties"]["id_ligne"], p["properties"]["motif"]) for p in points}
if motifs != {("L1", "risque_chute"), ("L1", "hauteur_excessive"), ("V1", "risque_chute"), ("V1", "hauteur_excessive")}:
    erreurs.append(f"motifs des points signalés : {sorted(motifs)}")
if not any("V1" in a and "sans données" in a for a in bilan["avertissements"]):
    erreurs.append("l'absence de LiDAR sur la fin de V1 aurait dû être signalée")

for e in erreurs:
    print("ÉCHEC", e)
print("vegetation-lidar-hd :", "tous les contrôles sont conformes" if not erreurs else f"{len(erreurs)} écart(s)")
sys.exit(1 if erreurs else 0)
