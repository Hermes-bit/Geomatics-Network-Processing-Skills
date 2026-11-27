# -*- coding: utf-8 -*-
"""
Crée un petit nuage de points FICTIF au format des dalles LiDAR HD classées (LAS 1.4, format de
point 6, classes IGN), et le GeoJSON des lignes correspondantes, en Lambert 93.

Usage : python3 generer_nuage_exemple.py [dossier]   (par défaut : le dossier de ce script)
Produit : nuage_exemple.las et lignes_exemple.geojson. Rien n'est tiré au hasard sans graine :
le résultat est identique à chaque exécution.

Scène (origine X0 = 900000, Y0 = 6500000) :
  * ligne électrique aérienne HTA « L1 » de (0, 0) à (200, 0) ;
  * voie ferrée « V1 » de (0, 60) à (250, 60) ; pas de données LiDAR au-delà de x = 210 ;
  * sol en pente douce, herbe (classe 3) partout ;
  * arbres et arbustes placés pour tester chaque règle (voir resultats_attendus.md).
"""

import json
import os
import sys

import numpy as np

X0, Y0 = 900000.0, 6500000.0

# (x, y, hauteur, rayon) en coordonnées relatives
ARBRES = [
    (40, 8, 12, 2.0),     # L1 gauche : 12 m à 8 m de l'axe -> risque de chute
    (120, -2, 5, 1.0),    # L1 droite : 5 m dans l'emprise de 5 m -> hauteur excessive
    (160, 20, 10, 2.0),   # L1 gauche : 10 m à 20 m -> rien à signaler
    (180, -12, 10, 1.5),  # L1 droite : 10 m à 12 m, marge 2 m -> à surveiller
    (70, 63, 2, 0.8),     # V1 gauche : 2 m à 3 m de l'axe (emprise 4 m, max 1,5 m) -> hauteur excessive
    (140, 70, 15, 2.0),   # V1 gauche : 15 m à 10 m -> risque de chute
]


def sol(x, y):
    return 100.0 + 0.02 * x + 0.01 * y


def generer(dossier):
    import laspy
    rng = np.random.default_rng(2154)
    pts = []
    # sol tous les 0,5 m, de -40 à 210 en x et de -40 à 100 en y
    gx, gy = np.meshgrid(np.arange(-40, 210, 0.5), np.arange(-40, 100, 0.5))
    gx, gy = gx.ravel() + rng.uniform(-0.1, 0.1, gx.size), gy.ravel() + rng.uniform(-0.1, 0.1, gy.size)
    pts.append(np.column_stack([gx, gy, sol(gx, gy), np.full(gx.size, 2)]))
    # herbe : 10 cm au-dessus du sol, un point sur quatre
    hx, hy = gx[::4], gy[::4]
    pts.append(np.column_stack([hx, hy, sol(hx, hy) + 0.1, np.full(hx.size, 3)]))
    # arbres : points répartis dans un cône
    for x, y, h, r in ARBRES:
        n = int(300 * h)
        z = rng.uniform(0.6, h, n)
        rayon = r * (1 - 0.7 * z / h) * np.sqrt(rng.uniform(0, 1, n))
        ang = rng.uniform(0, 2 * np.pi, n)
        px, py = x + rayon * np.cos(ang), y + rayon * np.sin(ang)
        z[-1] = h                                      # le sommet est bien à la hauteur annoncée
        px[-1], py[-1] = x, y
        classe = np.where(z > 1.5, 5, 4)
        pts.append(np.column_stack([px, py, sol(px, py) + z, classe]))
    p = np.vstack(pts)

    entete = laspy.LasHeader(point_format=6, version="1.4")
    entete.scales = np.array([0.01, 0.01, 0.01])
    entete.offsets = np.array([X0, Y0, 0.0])
    las = laspy.LasData(entete)
    las.x, las.y, las.z = p[:, 0] + X0, p[:, 1] + Y0, p[:, 2]
    las.classification = p[:, 3].astype(np.uint8)
    las.write(os.path.join(dossier, "nuage_exemple.las"))

    lignes = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2154"}},
        "features": [
            {"type": "Feature", "properties": {"id": "L1", "type": "ligne_aerienne", "nom": "Départ HTA fictif"},
             "geometry": {"type": "LineString", "coordinates": [[X0, Y0], [X0 + 200, Y0]]}},
            {"type": "Feature", "properties": {"id": "V1", "type": "voie_ferree", "nom": "Voie fictive"},
             "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + 60], [X0 + 250, Y0 + 60]]}},
        ],
    }
    with open(os.path.join(dossier, "lignes_exemple.geojson"), "w", encoding="utf-8") as f:
        json.dump(lignes, f, indent=1)
    return len(p)


if __name__ == "__main__":
    dossier = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    print(f"{generer(dossier)} points écrits dans {dossier}")
