# -*- coding: utf-8 -*-
"""
Crée le nuage de points FICTIF du chantier d'exemple, au format des dalles LiDAR HD classées
(LAS 1.4, format de point 6, classes IGN), et le GeoJSON des lignes à analyser avec le skill
vegetation-lidar-hd : la voie 830000 V1 et la ligne RTE 63 kV qui surplombe le chantier.

Usage : python3 generer_nuage_exemple.py [dossier]   (par défaut : le dossier de ce script)
Produit : nuage_chantier.las et lignes_chantier.geojson. Résultat identique à chaque exécution.

Mêmes coordonnées que donnees_exemple.sql : repère local (s, d), s le long de la voie dans le
sens des PK croissants, d à gauche, origine sur le saut de PK 15+400 = 15+650.
Le LiDAR s'arrête à s = 35 m : la fin de la voie analysée est « sans données ».
"""

import json
import os
import sys

import numpy as np

X0, Y0 = 805242.19, 6500234.77
UX, UY = 2000 / np.sqrt(4490000.0), 700 / np.sqrt(4490000.0)

# (s, d, hauteur, rayon)
ARBRES = [
    (-20, 9, 14, 2.0),    # voie, gauche : 14 m à 9 m de l'axe -> risque de chute
    (5, -24, 22, 2.0),    # voie, droite : 22 m à 24 m, marge 2 m -> à surveiller
    (-63, -30, 7, 1.0),   # ligne RTE : 7 m à 3 m de l'axe (emprise 5 m, max 4 m) -> hauteur excessive
]


def vers_l93(s, d):
    return X0 + s * UX - d * UY, Y0 + s * UY + d * UX


def sol(s, d):
    return 80.0 + 0.01 * s + 0.02 * d


def generer(dossier):
    import laspy
    rng = np.random.default_rng(2154)
    pts = []
    gs, gd = np.meshgrid(np.arange(-190, 35, 0.5), np.arange(-60, 60, 0.5))
    gs, gd = gs.ravel() + rng.uniform(-0.1, 0.1, gs.size), gd.ravel() + rng.uniform(-0.1, 0.1, gd.size)
    pts.append(np.column_stack([gs, gd, sol(gs, gd), np.full(gs.size, 2)]))
    hs, hd = gs[::4], gd[::4]
    pts.append(np.column_stack([hs, hd, sol(hs, hd) + 0.1, np.full(hs.size, 3)]))
    for s, d, h, r in ARBRES:
        n = int(300 * h)
        z = rng.uniform(0.6, h, n)
        rayon = r * (1 - 0.7 * z / h) * np.sqrt(rng.uniform(0, 1, n))
        ang = rng.uniform(0, 2 * np.pi, n)
        ps, pd = s + rayon * np.cos(ang), d + rayon * np.sin(ang)
        z[-1] = h
        ps[-1], pd[-1] = s, d
        pts.append(np.column_stack([ps, pd, sol(ps, pd) + z, np.where(z > 1.5, 5, 4)]))
    p = np.vstack(pts)
    x, y = vers_l93(p[:, 0], p[:, 1])

    entete = laspy.LasHeader(point_format=6, version="1.4")
    entete.scales = np.array([0.01, 0.01, 0.01])
    entete.offsets = np.array([X0, Y0, 0.0])
    las = laspy.LasData(entete)
    las.x, las.y, las.z = x, y, p[:, 2]
    las.classification = p[:, 3].astype(np.uint8)
    las.write(os.path.join(dossier, "nuage_chantier.las"))

    def ligne(points):
        return [[round(float(c), 2) for c in vers_l93(s, d)] for s, d in points]

    lignes = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2154"}},
        "features": [
            {"type": "Feature", "properties": {"id": "830000-V1", "type": "voie_ferree", "nom": "Ligne 830000 voie V1"},
             "geometry": {"type": "LineString", "coordinates": ligne([(-160, 0), (70, 0)])}},
            {"type": "Feature", "properties": {"id": "RTE-63kV", "type": "ligne_aerienne", "nom": "Ligne RTE 63 kV fictive"},
             "geometry": {"type": "LineString", "coordinates": ligne([(-80, -100), (-40, 100)])}},
        ],
    }
    with open(os.path.join(dossier, "lignes_chantier.geojson"), "w", encoding="utf-8") as f:
        json.dump(lignes, f, indent=1, ensure_ascii=False)
    return len(p)


if __name__ == "__main__":
    dossier = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    print(f"{generer(dossier)} points écrits dans {dossier}")
