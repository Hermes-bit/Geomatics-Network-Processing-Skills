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


def _vrai(v):
    """Booléen écrit en CSV par QGIS (1/0 ou true/false) -> 'true' / 'false'."""
    return "true" if str(v).lower() in ("1", "true", "t") else "false"


def tester_dtdict(tmp):
    print("=== proximite-dt-dict (QGIS)")
    from qgis.core import QgsVectorLayer
    d = os.path.join(RACINE, "skills", "proximite-dt-dict")
    algo, = charger_algorithmes(os.path.join(d, "qgis", "proximite_dt_dict.py"))
    g = os.path.join(d, "exemples", "chantier_exemple.gpkg")
    r = lancer(algo, {"EMPRISE": g + "|layername=emprise", "OUVRAGES": g + "|layername=ouvrages",
                      "EXPLOITANTS": g + "|layername=exploitants",
                      "SORTIE_OUVRAGES": os.path.join(tmp, "dt_ouvrages.gpkg"),
                      "SORTIE_EXPLOITANTS": os.path.join(tmp, "dt_exploitants.csv"),
                      "SORTIE_CONTROLE": os.path.join(tmp, "dt_controle.csv")})
    with open(os.path.join(tmp, "dt_exploitants.csv"), encoding="utf-8") as f:
        obtenu = "|".join(sorted("%s:%s:%s" % (e["exploitant"], e["situation_la_plus_proche"], _vrai(e["ic_a_prevoir"]))
                                 for e in csv.DictReader(f)))
    attendu = ("Chaleur Urbaine:zone_incertitude:true|Enedis:dans_emprise:true|GRDF:zone_incertitude:false|"
               "Métropole:proximite:false|Orange:proximite:false|RTE:proximite:false|"
               "Syndicat intercommunal:dans_emprise:false")
    verifier(obtenu == attendu, "exploitants et situations identiques au script SQL (obtenu %s)" % obtenu)
    ouvr = QgsVectorLayer(os.path.join(tmp, "dt_ouvrages.gpkg"), "o", "ogr")
    obtenu = ",".join("%s:%s" % (f["id"], f["situation"]) for f in sorted(ouvr.getFeatures(), key=lambda f: int(f["id"])))
    verifier(obtenu == "1:dans_emprise,2:zone_incertitude,3:proximite,4:fuseau_aerien,5:proximite,7:proximite,"
                       "8:zone_incertitude,9:dans_emprise", "ouvrages retenus : %s" % obtenu)
    with open(os.path.join(tmp, "dt_controle.csv"), encoding="utf-8") as f:
        ctrl = {c["controle"]: c for c in csv.DictReader(f)}
    verifier(_vrai(ctrl["écart entre polygones"]["conforme"]) == "false", "écart de 240 m entre polygones signalé")
    rte = [f["alertes"] for f in ouvr.getFeatures() if f["id"] == "5"][0]
    verifier("exemption" not in rte, "pas d'exemption des 3 m pour la ligne RTE 63 kV")


def tester_impact(tmp):
    print("=== analyse-impact-chantier (QGIS)")
    from qgis.core import QgsVectorLayer
    s = os.path.join(RACINE, "skills")
    algo, = charger_algorithmes(os.path.join(s, "analyse-impact-chantier", "qgis", "analyse_impact_chantier.py"))
    charger_algorithmes(os.path.join(s, "referencement-pk-ferroviaire", "qgis", "referencement_pk_ferroviaire.py"))
    e = os.path.join(s, "analyse-impact-chantier", "exemples")
    g = os.path.join(e, "chantier_exemple.gpkg")
    pk = os.path.join(s, "referencement-pk-ferroviaire", "exemples", "ligne_exemple.gpkg")
    sorties = {n: os.path.join(tmp, "impact_%s.gpkg" % n.lower()) for n in (
        "SORTIE_RISQUES", "SORTIE_OUVRAGES", "SORTIE_VOIES", "SORTIE_VEGETATION", "SORTIE_PARCELLES", "SORTIE_ZONE")}
    sorties["SORTIE_EXPLOITANTS"] = os.path.join(tmp, "impact_exploitants.csv")
    pdf, carte = os.path.join(tmp, "dossier_impact.pdf"), os.path.join(tmp, "carte_impact.html")
    lancer(algo, dict({
        "EMPRISE": g + "|layername=emprise", "NOM_CHANTIER": "Raccordement HTA et traversée de la ligne 830000",
        "OUVRAGES": g + "|layername=ouvrages", "EXPLOITANTS": g + "|layername=exploitants",
        "AXES": pk + "|layername=axes", "CODE_LIGNE": "830000", "VOIE": "V1", "BORNES": pk + "|layername=bornes_pk",
        "SAUTS": pk + "|layername=sauts_pk", "VEGETATION": os.path.join(e, "troncons_vegetation_exemple.geojson"),
        "PARCELLES": g + "|layername=parcelles", "PROPRIETAIRES": g + "|layername=proprietaires_pm",
        "DOSSIER_PDF": pdf, "CARTE_HTML": carte}, **sorties))

    risques = sorted(QgsVectorLayer(sorties["SORTIE_RISQUES"], "r", "ogr").getFeatures(), key=lambda f: f["id"])
    obtenu = "|".join("%s:%s%s" % (f["niveau"], f["theme"], "" if f["theme"] == "ferroviaire" else ":" + f["objet"])
                      for f in risques)
    attendu = ("1:ferroviaire|1:voisinage électrique:Ouvrage 4 : electricite aérien, 63 kV|"
               "1:voisinage électrique:Ouvrage 5 : ferroviaire aérien, 25 kV|"
               "1:réseaux:Ouvrage 1 : electricite souterrain, classe B, 20 kV|"
               "1:réseaux:Ouvrage 6 : ferroviaire souterrain, classe C|2:déclaration:Emprise : écart entre polygones|"
               "2:réseaux:Ouvrage 2 : gaz souterrain, classe A|2:végétation:Ligne 830000 voie V1, tronçon 6 gauche|"
               "2:végétation:Ligne RTE 63 kV fictive, tronçon 3 droite|3:réseaux:Ouvrage 3 : telecom souterrain, classe C|"
               "3:végétation:Ligne 830000 voie V1, tronçon 7 droite|3:foncier:Parcelle AB 0101 (99001)|"
               "3:foncier:Parcelle AB 0102 (99001)|3:foncier:Parcelle AB 0103 (99001)|3:foncier:Parcelle AB 0104 (99001)|"
               "3:foncier:Parcelle AC 0202 (99001)|4:végétation:Ligne 830000 voie V1, tronçon 9 gauche|"
               "4:végétation:Ligne 830000 voie V1, tronçon 9 droite|4:foncier:Parcelle AB 0105 (99001)|"
               "4:foncier:Parcelle AC 0203 (99001)")
    verifier(obtenu == attendu, "registre des risques identique au script SQL (20 risques)")
    if obtenu != attendu:
        print("      obtenu :", obtenu)
    voie = next(QgsVectorLayer(sorties["SORTIE_VOIES"], "v", "ogr").getFeatures())
    pk_m = lambda t: int(t.split("+")[0]) * 1000 + float(t.split("+")[1])  # noqa: E731
    verifier(abs(pk_m(voie["pk_debut"]) - 15264.4) <= 0.5 and abs(pk_m(voie["pk_fin"]) - 15699.1) <= 0.5,
             "voie : PK %s à %s (attendu 15+264.4 à 15+699.1, à 0,5 m près)" % (voie["pk_debut"], voie["pk_fin"]))
    verifier((voie["pk_emprise_debut"], voie["pk_emprise_fin"]) == ("15+674", "15+676"),
             "voie dans l'emprise : PK %s à %s" % (voie["pk_emprise_debut"], voie["pk_emprise_fin"]))
    verifier("lacune de PK 15+400 = 15+650" in voie["avertissement"], "saut de PK dans la section signalé")
    with open(sorties["SORTIE_EXPLOITANTS"], encoding="utf-8") as f:
        obtenu = "|".join(sorted("%s:%s" % (x["exploitant"], x["niveau_max"]) for x in csv.DictReader(f)))
    verifier(obtenu == "Enedis:1|GRDF:2|Orange:3|RTE:1|SNCF Réseau:1", "exploitants et niveau max : %s" % obtenu)
    parc = sorted(QgsVectorLayer(sorties["SORTIE_PARCELLES"], "p", "ogr").getFeatures(), key=lambda f: f["id"])
    obtenu = "|".join("%s:%s:%s" % (f["id"][-6:], f["situation"], f["surface_emprise_m2"]) for f in parc)
    verifier(obtenu == "AB0101:occupee:104.0|AB0102:occupee:400.0|AB0103:occupee:280.0|AB0104:occupee:340.0|"
                       "AB0105:riveraine:0.0|AC0202:occupee:216.0|AC0203:contact_negligeable:1.2",
             "parcelles et surfaces dans l'emprise")
    verifier(os.path.exists(pdf) and lire_debut(pdf) == b"%PDF-", "dossier PDF écrit")
    with open(carte, encoding="utf-8") as f:
        verifier(f.read().count('"gravite"') == 20, "carte HTML écrite avec les 20 risques")


def lire_debut(chemin):
    with open(chemin, "rb") as f:
        return f.read(5)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tester_topologie(tmp)
        tester_pk(tmp)
        tester_dtdict(tmp)
        tester_impact(tmp)
    print("\n%s" % ("Tout est conforme aux résultats attendus." if not erreurs
                    else "%d écart(s) avec les résultats attendus." % len(erreurs)))
    sys.exit(1 if erreurs else 0)
