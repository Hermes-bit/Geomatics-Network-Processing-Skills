# -*- coding: utf-8 -*-
"""
Teste les versions QGIS des skills sur les jeux d'exemple, sans ouvrir QGIS, et compare
avec les résultats attendus (exemples/resultats_attendus.md de chaque skill).

Usage (Python de QGIS) :  python3 outils/tester_qgis.py
Sous Windows : python-qgis outils\\tester_qgis.py dans l'« OSGeo4W Shell ».
Code de sortie 0 si tout est conforme, 1 sinon.
"""

import csv
import os
import sys
import tempfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "outils"))
from qgis_sans_interface import charger_algorithmes, lancer  # noqa: E402

erreurs = []


def verifier(condition, message):
    print("   ", "ok    " if condition else "ÉCHEC ", message)
    if not condition:
        erreurs.append(message)


def lire_csv(chemin):
    with open(chemin, encoding="utf-8") as f:
        return {r.get("id") or "%s/%s" % (r["gravite"], r["type"]): r for r in csv.DictReader(f)}


def tester_topologie(tmp):
    print("=== controle-topologie-reseau (QGIS)")
    d = os.path.join(RACINE, "skills", "controle-topologie-reseau")
    algo, = charger_algorithmes(os.path.join(d, "qgis", "controle_topologie_reseau.py"))
    g = os.path.join(d, "exemples", "reseau_exemple.gpkg")
    lancer(algo, {
        "TRONCONS": g + "|layername=troncons", "CHAMP_ID": "id", "CHAMP_TENSION": "tension_kv",
        "CHAMP_POSE": "pose", "CHAMP_ETAT": "etat_exploitation",
        "POSTES": g + "|layername=postes", "CHAMP_POSTE_ID": "id", "CHAMP_POSTE_NOM": "nom",
        "CHAMP_POSTE_TYPE": "type",
        "SORTIE_POINTS": os.path.join(tmp, "anomalies_points.gpkg"),
        "SORTIE_LIGNES": os.path.join(tmp, "anomalies_lignes.gpkg"),
        "SORTIE_RESUME": os.path.join(tmp, "resume.csv")})
    obtenu = {k: int(v["nombre"]) for k, v in lire_csv(os.path.join(tmp, "resume.csv")).items()}
    attendu = {
        "majeure/boucle_fermee_radial": 1, "majeure/composante_isolee": 3, "majeure/croisement_sans_noeud": 1,
        "majeure/doublon_geometrique": 1, "majeure/poste_isole": 1, "majeure/quasi_connexion": 1,
        "mineure/attribut_incoherent": 1, "mineure/attribut_manquant": 1, "mineure/extremite_pendante": 4,
        "mineure/tension_incoherente_noeud": 1, "mineure/troncon_trop_court": 1,
        "info/franchissement": 1, "info/troncon_multi_fusionne": 1}
    for k in sorted(set(attendu) | set(obtenu)):
        verifier(obtenu.get(k) == attendu.get(k), "%s : %s (attendu %s)" % (k, obtenu.get(k), attendu.get(k)))

    from qgis.core import QgsVectorLayer
    lignes = QgsVectorLayer(os.path.join(tmp, "anomalies_lignes.gpkg"), "l", "ogr")
    boucle = [f["id_objet"] for f in lignes.getFeatures() if f["type"] == "boucle_fermee_radial"]
    verifier(boucle == ["3,6,7,8,15"], "boucle fermée formée par les tronçons 3,6,7,8,15 : %s" % boucle)
    points = QgsVectorLayer(os.path.join(tmp, "anomalies_points.gpkg"), "p", "ogr")
    franch = [f["id_objet"] for f in points.getFeatures() if f["type"] == "franchissement"]
    verifier(franch == ["2/13"], "franchissement 2/13 (souterrain sous aérien) non signalé comme erreur")

    # Rapport PDF et carte HTML à partir des anomalies produites
    import subprocess
    pdf, carte = os.path.join(tmp, "rapport.pdf"), os.path.join(tmp, "carte.html")
    r = subprocess.run([sys.executable, os.path.join(d, "rapport", "rapport_anomalies.py"),
                        "--reseau", g + "|layername=troncons", "--postes", g + "|layername=postes",
                        "--anomalies", os.path.join(tmp, "anomalies_points.gpkg"),
                        "--anomalies", os.path.join(tmp, "anomalies_lignes.gpkg"),
                        "--pdf", pdf, "--html", carte], capture_output=True, text=True)
    verifier(r.returncode == 0 and "18 anomalie(s)" in r.stdout, "rapport : 18 anomalies reprises")
    verifier(os.path.exists(pdf) and open(pdf, "rb").read(5) == b"%PDF-", "rapport PDF écrit")
    verifier(os.path.exists(carte) and open(carte, encoding="utf-8").read().count('"gravite"') == 18,
             "carte HTML écrite avec les 18 anomalies")


def tester_pk(tmp):
    print("=== referencement-pk-ferroviaire (QGIS)")
    from qgis.core import QgsVectorLayer
    d = os.path.join(RACINE, "skills", "referencement-pk-ferroviaire")
    algo, = charger_algorithmes(os.path.join(d, "qgis", "referencement_pk_ferroviaire.py"))
    e = os.path.join(d, "exemples")
    g = os.path.join(e, "ligne_exemple.gpkg")
    uri = "file://%s?delimiter=,&xField=x&yField=y&crs=EPSG:2154" % os.path.join(e, "points_a_localiser.csv")
    points = QgsVectorLayer(uri, "points", "delimitedtext")
    lancer(algo, {
        "AXES": g + "|layername=axes", "CHAMP_LIGNE_AXE": "code_ligne", "CODE_LIGNE": "830000",
        "CHAMP_VOIE": "voie", "VOIE": "V1",
        "BORNES": g + "|layername=bornes_pk", "CHAMP_LIGNE_BORNE": "code_ligne", "CHAMP_PK_BORNE": "pk",
        "SAUTS": g + "|layername=sauts_pk", "CHAMP_LIGNE_SAUT": "code_ligne",
        "CHAMP_PK_AMONT": "pk_amont", "CHAMP_PK_AVAL": "pk_aval",
        "PK_ENTREE": os.path.join(e, "pk_a_convertir.csv"), "CHAMP_PK": "pk", "CHAMP_DECALAGE": "decalage_m",
        "POINTS": points,
        "EVENEMENTS": os.path.join(e, "evenements_lineaires.csv"), "CHAMP_PK_DEBUT": "pk_debut",
        "CHAMP_PK_FIN": "pk_fin",
        "SORTIE_PK_XY": os.path.join(tmp, "pk_vers_xy.csv"), "SORTIE_XY_PK": os.path.join(tmp, "xy_vers_pk.csv"),
        "SORTIE_EVENEMENTS": os.path.join(tmp, "evenements.csv"), "SORTIE_CALAGE": os.path.join(tmp, "calage.csv")})

    r = lire_csv(os.path.join(tmp, "pk_vers_xy.csv"))
    for i, x, y in (("E01", "801236.7", "6500185.51"), ("E02", "804488.05", "6499966.05"),
                    ("E04", "806607.83", "6500351.13")):
        verifier((float(r[i]["x_l93"]), float(r[i]["y_l93"])) == (float(x), float(y)),
                 "%s -> %s, %s (obtenu %s, %s)" % (i, x, y, r[i]["x_l93"], r[i]["y_l93"]))
    verifier("lacune 15+400 = 15+650" in r["E03"]["avertissement"], "E03 : PK dans la lacune signalé")
    verifier("hors de la ligne (10+000 à 20+213.2)" in r["E05"]["avertissement"], "E05 : PK hors de la ligne signalé")

    r = lire_csv(os.path.join(tmp, "xy_vers_pk.csv"))
    for i, pk, dist, dec in (("P01", "12+499.8", 0, 0), ("P02", "15+400", 6, 6), ("P03", "15+800", 3, -3),
                             ("P04", "18+201", 35, 35), ("P05", "19+948.8", 2, 2)):
        verifier((r[i]["pk"], float(r[i]["distance_axe_m"]), float(r[i]["decalage_m"])) == (pk, dist, dec),
                 "%s -> %s, %s m, décalage %s (obtenu %s, %s, %s)" % (
                     i, pk, dist, dec, r[i]["pk"], r[i]["distance_axe_m"], r[i]["decalage_m"]))
    verifier("saut de PK 15+400 = 15+650" in r["P02"]["avertissement"], "P02 : au droit du saut de PK")
    verifier("rattachement douteux" in r["P04"]["avertissement"], "P04 : point à 35 m signalé")

    r = lire_csv(os.path.join(tmp, "evenements.csv"))
    verifier(float(r["L01"]["longueur_terrain_m"]) == 1298.9, "L01 : 1298.9 m (obtenu %s)" % r["L01"]["longueur_terrain_m"])
    verifier(float(r["L02"]["longueur_terrain_m"]) == 950.4, "L02 : 950.4 m (obtenu %s)" % r["L02"]["longueur_terrain_m"])
    verifier("lacune" in r["L02"]["avertissement"], "L02 : contient la lacune")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tester_topologie(tmp)
        tester_pk(tmp)
    print("\n%s" % ("Tout est conforme aux résultats attendus." if not erreurs
                    else "%d écart(s) avec les résultats attendus." % len(erreurs)))
    sys.exit(1 if erreurs else 0)
