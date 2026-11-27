# -*- coding: utf-8 -*-
"""
Végétation près des lignes électriques aériennes et des voies ferrées, à partir des nuages
de points classés LiDAR HD de l'IGN (LAZ / COPC, Lambert 93, altitudes IGN69).

Pour chaque ligne, le script découpe un couloir en tronçons (25 m par défaut, de chaque côté),
calcule la hauteur de la végétation au-dessus du sol et signale :
  * hauteur_excessive : végétation plus haute que h_max_emprise_m dans l'emprise (près de l'axe) ;
  * risque_chute      : arbre assez haut pour atteindre l'axe en tombant (hauteur > distance - marge) ;
  * à surveiller      : arbre à moins de marge_surveillance_m de pouvoir atteindre l'axe, ou
                        végétation à moins de 1 m de la hauteur maximale dans l'emprise.

Usage :
  python3 vegetation_lidar.py --lignes lignes.geojson --sortie resultats/ dalle1.copc.laz [dalle2.laz ...]
  python3 vegetation_lidar.py --parametres mes_regles.json ...

Entrées :
  lignes.geojson : LineString ou MultiLineString en Lambert 93 (EPSG:2154), avec les propriétés
                   « id » et « type » (ligne_aerienne ou voie_ferree). Les propriétés couloir_m,
                   emprise_m, h_max_emprise_m, marge_chute_m remplacent les valeurs par défaut.
Sorties (dossier --sortie) :
  troncons_vegetation.csv / .geojson : un tronçon par ligne, côté et pas de 25 m, avec sa priorité ;
  points_signales.geojson            : cellules de 2 m où un point est signalé (pour QGIS) ;
  bilan.json                         : paramètres, dalles, couverture et avertissements.

Dépendances : numpy et laspy (pip install "laspy[lazrs]" pour lire les .laz et .copc.laz).
"""

import argparse
import csv
import json
import math
import os
import sys
import warnings

import numpy as np

# Codes de classification du LiDAR HD (IGN)
CLASSES_LIDAR_HD = {
    1: "non classé", 2: "sol", 3: "végétation basse (0-50 cm)", 4: "végétation moyenne (50 cm-1,50 m)",
    5: "végétation haute (> 1,50 m)", 6: "bâtiment", 9: "eau", 17: "tablier de pont",
    64: "sursol pérenne", 66: "points virtuels", 67: "divers bâtis",
}

# Valeurs de départ, à remplacer par les règles du gestionnaire (voir SKILL.md).
PARAMETRES_DEFAUT = {
    "pas_m": 25.0,                 # longueur des tronçons le long de la ligne
    "cellule_sol_m": 1.0,          # maille du modèle de sol calculé à partir des points « sol »
    "cellule_points_m": 2.0,       # maille des points signalés exportés
    "classes_vegetation": [4, 5],  # végétation moyenne et haute ; ajouter 3 pour la basse
    "classes_sol": [2, 9],         # sol et eau
    "types": {
        "ligne_aerienne": {"couloir_m": 30.0, "emprise_m": 5.0, "h_max_emprise_m": 4.0, "marge_chute_m": 1.0,
                           "marge_surveillance_m": 3.0},
        "voie_ferree":    {"couloir_m": 25.0, "emprise_m": 4.0, "h_max_emprise_m": 1.5, "marge_chute_m": 1.0,
                           "marge_surveillance_m": 3.0},
    },
}


# ---------------------------------------------------------------------------
# Lecture des entrées
# ---------------------------------------------------------------------------
def lire_lignes(chemin, parametres):
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    crs = (donnees.get("crs") or {}).get("properties", {}).get("name", "")
    if crs and "2154" not in crs:
        raise SystemExit(f"{chemin} est en {crs} : reprojeter les lignes en Lambert 93 (EPSG:2154)")
    lignes = []
    for i, entite in enumerate(donnees["features"], 1):
        props = entite.get("properties") or {}
        geom = entite["geometry"]
        type_ligne = props.get("type", "ligne_aerienne")
        if type_ligne not in parametres["types"]:
            raise SystemExit(f"Type « {type_ligne} » inconnu (attendu : {', '.join(parametres['types'])})")
        regles = dict(parametres["types"][type_ligne])
        for cle in regles:
            if props.get(cle) is not None:
                regles[cle] = float(props[cle])
        parties = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for k, coords in enumerate(parties):
            xy = np.asarray(coords, dtype=float)[:, :2]
            if abs(xy[0, 0]) < 1000 and abs(xy[0, 1]) < 1000:
                raise SystemExit(f"{chemin} : coordonnées en degrés ? Reprojeter en Lambert 93 (EPSG:2154)")
            lignes.append({
                "id": str(props.get("id", i)) + (f"-{k + 1}" if len(parties) > 1 else ""),
                "type": type_ligne, "nom": props.get("nom", ""), "regles": regles, "xy": xy,
            })
    return lignes


def lire_nuages(chemins, emprise):
    try:
        import laspy
    except ImportError:
        raise SystemExit('laspy manque : pip install "laspy[lazrs]"')
    xmin, ymin, xmax, ymax = emprise
    morceaux, dalles = [], []
    for chemin in chemins:
        with laspy.open(chemin) as lecteur:
            h = lecteur.header
            info = {
                "fichier": os.path.basename(chemin), "nb_points": int(h.point_count),
                "date": str(h.creation_date) if h.creation_date else None,
                "crs": None,
            }
            try:
                crs = h.parse_crs()
                info["crs"] = crs.to_string() if crs else None
            except Exception:
                pass
            dalles.append(info)
            if h.maxs[0] < xmin or h.mins[0] > xmax or h.maxs[1] < ymin or h.mins[1] > ymax:
                info["utilisee"] = False
                continue
            info["utilisee"] = True
            for bloc in lecteur.chunk_iterator(2_000_000):
                x, y = np.asarray(bloc.x), np.asarray(bloc.y)
                garde = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
                if garde.any():
                    morceaux.append(np.column_stack([x[garde], y[garde], np.asarray(bloc.z)[garde],
                                                     np.asarray(bloc.classification)[garde]]))
    if not morceaux:
        return np.empty((0, 4)), dalles
    return np.vstack(morceaux), dalles


# ---------------------------------------------------------------------------
# Modèle de sol et hauteur de la végétation
# ---------------------------------------------------------------------------
def modele_sol(points_sol, emprise, cellule):
    """Grille du point sol le plus bas par cellule, trous bouchés par la moyenne des voisins."""
    xmin, ymin, xmax, ymax = emprise
    nx, ny = int(math.ceil((xmax - xmin) / cellule)) + 1, int(math.ceil((ymax - ymin) / cellule)) + 1
    grille = np.full((ny, nx), np.inf)
    if len(points_sol):
        ix = ((points_sol[:, 0] - xmin) / cellule).astype(int)
        iy = ((points_sol[:, 1] - ymin) / cellule).astype(int)
        np.minimum.at(grille, (iy, ix), points_sol[:, 2])
    grille[np.isinf(grille)] = np.nan
    remplies_au_depart = np.isfinite(grille).mean() if grille.size else 0
    for _ in range(50):                      # bouche les trous (sous les arbres denses, bâtiments)
        trous = np.isnan(grille)
        if not trous.any() or trous.all():
            break
        p = np.pad(grille, 1, constant_values=np.nan)
        voisins = np.stack([p[1:-1, :-2], p[1:-1, 2:], p[:-2, 1:-1], p[2:, 1:-1]])
        if not np.isfinite(voisins).any():
            break
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            moyenne = np.nanmean(voisins, axis=0)
        grille[trous] = moyenne[trous]
    return grille, remplies_au_depart


def hauteur_sol(grille, emprise, cellule, x, y):
    xmin, ymin = emprise[0], emprise[1]
    ix = np.clip(((x - xmin) / cellule).astype(int), 0, grille.shape[1] - 1)
    iy = np.clip(((y - ymin) / cellule).astype(int), 0, grille.shape[0] - 1)
    return grille[iy, ix]


# ---------------------------------------------------------------------------
# Géométrie : position des points par rapport à la ligne
# ---------------------------------------------------------------------------
def projeter(xy_ligne, px, py):
    """Distance horizontale, abscisse curviligne et côté (+1 gauche, -1 droite) du point le plus proche."""
    a, b = xy_ligne[:-1], xy_ligne[1:]
    seg = b - a
    long_seg = np.hypot(seg[:, 0], seg[:, 1])
    cumul = np.concatenate([[0.0], np.cumsum(long_seg)])
    meilleure_d = np.full(px.shape, np.inf)
    abscisse = np.zeros(px.shape)
    cote = np.zeros(px.shape)
    for i in range(len(seg)):
        if long_seg[i] == 0:
            continue
        t = ((px - a[i, 0]) * seg[i, 0] + (py - a[i, 1]) * seg[i, 1]) / long_seg[i] ** 2
        t = np.clip(t, 0, 1)
        cx, cy = a[i, 0] + t * seg[i, 0], a[i, 1] + t * seg[i, 1]
        d = np.hypot(px - cx, py - cy)
        mieux = d < meilleure_d
        meilleure_d[mieux] = d[mieux]
        abscisse[mieux] = cumul[i] + t[mieux] * long_seg[i]
        produit = seg[i, 0] * (py - a[i, 1]) - seg[i, 1] * (px - a[i, 0])
        cote[mieux] = np.where(produit[mieux] >= 0, 1, -1)
    return meilleure_d, abscisse, cote, cumul[-1]


def point_a_abscisse(xy_ligne, s):
    seg = np.diff(xy_ligne, axis=0)
    long_seg = np.hypot(seg[:, 0], seg[:, 1])
    cumul = np.concatenate([[0.0], np.cumsum(long_seg)])
    i = min(max(np.searchsorted(cumul, s, side="right") - 1, 0), len(seg) - 1)
    t = 0 if long_seg[i] == 0 else (s - cumul[i]) / long_seg[i]
    return xy_ligne[i] + t * seg[i]


def sous_ligne(xy_ligne, s0, s1):
    seg = np.diff(xy_ligne, axis=0)
    cumul = np.concatenate([[0.0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
    interieurs = [xy_ligne[i] for i in range(len(xy_ligne)) if s0 < cumul[i] < s1]
    return np.array([point_a_abscisse(xy_ligne, s0)] + interieurs + [point_a_abscisse(xy_ligne, s1)])


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------
def analyser(lignes, nuage, parametres):
    pas = parametres["pas_m"]
    couloir_max = max(l["regles"]["couloir_m"] for l in lignes)
    toutes = np.vstack([l["xy"] for l in lignes])
    emprise = (toutes[:, 0].min() - couloir_max, toutes[:, 1].min() - couloir_max,
               toutes[:, 0].max() + couloir_max, toutes[:, 1].max() + couloir_max)

    classes = nuage[:, 3].astype(int) if len(nuage) else np.array([], dtype=int)
    sol = nuage[np.isin(classes, parametres["classes_sol"])]
    veg = nuage[np.isin(classes, parametres["classes_vegetation"])]
    grille, part_sol = modele_sol(sol, emprise, parametres["cellule_sol_m"])
    h_veg = veg[:, 2] - hauteur_sol(grille, emprise, parametres["cellule_sol_m"], veg[:, 0], veg[:, 1]) if len(veg) else np.array([])

    troncons, signales, avertissements = [], [], []
    if len(sol) == 0:
        avertissements.append("aucun point sol (classe 2) : nuage non classé ou hors des lignes")
    for ligne in lignes:
        r = ligne["regles"]
        xy = ligne["xy"]
        # préfiltre rectangle
        bx = (veg[:, 0] >= xy[:, 0].min() - r["couloir_m"]) & (veg[:, 0] <= xy[:, 0].max() + r["couloir_m"]) & \
             (veg[:, 1] >= xy[:, 1].min() - r["couloir_m"]) & (veg[:, 1] <= xy[:, 1].max() + r["couloir_m"]) if len(veg) else np.array([], bool)
        px, py, hh = veg[bx, 0], veg[bx, 1], h_veg[bx]
        d, s, cote, longueur = projeter(xy, px, py)
        dans = d <= r["couloir_m"]
        px, py, hh, d, s, cote = px[dans], py[dans], hh[dans], d[dans], s[dans], cote[dans]

        excessive = (d <= r["emprise_m"]) & (hh > r["h_max_emprise_m"])
        chute = (d > r["emprise_m"]) & (hh > d - r["marge_chute_m"])

        # couverture : part de la ligne avec des points sol à proximité
        dsol, ssol, _, _ = projeter(xy, sol[:, 0], sol[:, 1]) if len(sol) else (np.array([]), np.array([]), None, None)
        couverts = np.unique((ssol[dsol <= r["couloir_m"]] // pas).astype(int)) if len(sol) else np.array([])
        nb_pas = max(int(math.ceil(longueur / pas)), 1)
        if len(couverts) < nb_pas:
            avertissements.append(
                f"ligne {ligne['id']} : {nb_pas - len(couverts)} tronçon(s) de {pas:g} m sans données LiDAR (dalle manquante ?)")

        for k in range(nb_pas):
            s0, s1 = k * pas, min((k + 1) * pas, longueur)
            for c, nom_cote in ((1, "gauche"), (-1, "droite")):
                m = (s >= s0) & ((s < s1) | ((k == nb_pas - 1) & (s <= s1))) & (cote == c)
                n_exc, n_chute = int((m & excessive).sum()), int((m & chute).sum())
                if m.any():
                    h_max = float(hh[m].max())
                    d_min = float(d[m].min())
                    marge = float((d[m] - hh[m]).min())  # < 0 : un arbre atteint l'axe en tombant
                else:
                    h_max = d_min = marge = None
                couvert = k in set(couverts.tolist())
                if not couvert:
                    priorite = "sans_donnees"
                elif n_exc or n_chute:
                    priorite = "1_intervenir"
                elif (marge is not None and marge < r["marge_surveillance_m"]) or \
                        (m & (d <= r["emprise_m"]) & (hh > r["h_max_emprise_m"] - 1)).any():
                    priorite = "2_surveiller"
                else:
                    priorite = "3_rien_a_signaler"
                troncons.append({
                    "id_ligne": ligne["id"], "type": ligne["type"], "nom": ligne["nom"], "troncon": k + 1,
                    "abscisse_debut_m": round(s0, 1), "abscisse_fin_m": round(s1, 1), "cote": nom_cote,
                    "nb_points_vegetation": int(m.sum()),
                    "hauteur_max_m": None if h_max is None else round(h_max, 1),
                    "distance_min_m": None if d_min is None else round(d_min, 1),
                    "marge_chute_min_m": None if marge is None else round(marge, 1),
                    "nb_points_hauteur_excessive": n_exc, "nb_points_risque_chute": n_chute,
                    "priorite": priorite, "geom": sous_ligne(xy, s0, s1),
                })
        # points signalés regroupés en cellules
        cel = parametres["cellule_points_m"]
        for motif, masque in (("hauteur_excessive", excessive), ("risque_chute", chute)):
            if not masque.any():
                continue
            cx = np.floor(px[masque] / cel) * cel + cel / 2
            cy = np.floor(py[masque] / cel) * cel + cel / 2
            cles = np.round(cx * 1e3) * 1e7 + np.round(cy)
            for cle in np.unique(cles):
                sel = cles == cle
                signales.append({
                    "id_ligne": ligne["id"], "motif": motif,
                    "hauteur_max_m": round(float(hh[masque][sel].max()), 1),
                    "distance_m": round(float(d[masque][sel].min()), 1),
                    "nb_points": int(sel.sum()), "x": float(cx[sel][0]), "y": float(cy[sel][0]),
                })
    return troncons, signales, avertissements, {"part_cellules_sol": round(float(part_sol), 3),
                                                "nb_points_sol": int(len(sol)), "nb_points_vegetation": int(len(veg))}


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
def wkt_ligne(xy):
    return "LINESTRING(" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in xy) + ")"


def ecrire(dossier, troncons, signales, bilan):
    os.makedirs(dossier, exist_ok=True)
    champs = [k for k in troncons[0] if k != "geom"] + ["wkt_l93"] if troncons else []
    with open(os.path.join(dossier, "troncons_vegetation.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        for t in troncons:
            ligne = {k: v for k, v in t.items() if k != "geom"}
            ligne["wkt_l93"] = wkt_ligne(t["geom"])
            w.writerow(ligne)
    crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2154"}}
    with open(os.path.join(dossier, "troncons_vegetation.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "crs": crs, "features": [
            {"type": "Feature", "properties": {k: v for k, v in t.items() if k != "geom"},
             "geometry": {"type": "LineString", "coordinates": np.round(t["geom"], 2).tolist()}} for t in troncons]},
            f, ensure_ascii=False)
    with open(os.path.join(dossier, "points_signales.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "crs": crs, "features": [
            {"type": "Feature", "properties": {k: v for k, v in p.items() if k not in ("x", "y")},
             "geometry": {"type": "Point", "coordinates": [p["x"], p["y"]]}} for p in signales]},
            f, ensure_ascii=False)
    with open(os.path.join(dossier, "bilan.json"), "w", encoding="utf-8") as f:
        json.dump(bilan, f, ensure_ascii=False, indent=2)


def principal(arguments=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nuages", nargs="+", help="dalles LiDAR HD classées (.laz, .copc.laz, .las)")
    ap.add_argument("--lignes", required=True, help="GeoJSON des lignes en Lambert 93")
    ap.add_argument("--sortie", default="resultats_vegetation", help="dossier de sortie")
    ap.add_argument("--parametres", help="JSON qui remplace tout ou partie des paramètres par défaut")
    a = ap.parse_args(arguments)

    parametres = json.loads(json.dumps(PARAMETRES_DEFAUT))
    if a.parametres:
        with open(a.parametres, encoding="utf-8") as f:
            perso = json.load(f)
        for cle, val in perso.items():
            if cle == "types":
                for t, regles in val.items():
                    parametres["types"].setdefault(t, {}).update(regles)
            else:
                parametres[cle] = val

    lignes = lire_lignes(a.lignes, parametres)
    couloir = max(l["regles"]["couloir_m"] for l in lignes)
    toutes = np.vstack([l["xy"] for l in lignes])
    emprise = (toutes[:, 0].min() - couloir, toutes[:, 1].min() - couloir,
               toutes[:, 0].max() + couloir, toutes[:, 1].max() + couloir)
    nuage, dalles = lire_nuages(a.nuages, emprise)
    troncons, signales, avertissements, stats = analyser(lignes, nuage, parametres)
    for dalle in dalles:
        if dalle["crs"] and "2154" not in dalle["crs"] and "Lambert-93" not in dalle["crs"] and "Lambert 93" not in dalle["crs"]:
            avertissements.append(f"{dalle['fichier']} : SCR {dalle['crs']} (Lambert 93 attendu)")
    if not any(d.get("utilisee") for d in dalles):
        avertissements.append("aucune dalle ne recouvre les lignes")

    compte = {}
    for t in troncons:
        compte[t["priorite"]] = compte.get(t["priorite"], 0) + 1
    bilan = {"parametres": parametres, "dalles": dalles, "statistiques": stats,
             "troncons_par_priorite": dict(sorted(compte.items())), "nb_points_signales": len(signales),
             "avertissements": avertissements}
    ecrire(a.sortie, troncons, signales, bilan)
    print(json.dumps({k: bilan[k] for k in ("troncons_par_priorite", "nb_points_signales", "avertissements")},
                     ensure_ascii=False, indent=2))
    return bilan


if __name__ == "__main__":
    principal()
