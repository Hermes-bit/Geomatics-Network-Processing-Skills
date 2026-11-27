# -*- coding: utf-8 -*-
"""
Test automatique du skill analyse-bilan-electrique sur ses deux jeux d'exemple.
Usage : python3 exemples/test_analyse_bilan.py   (code de sortie 0 si tout est conforme)
"""
import os
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "scripts"))
import analyser_bilan  # noqa: E402

erreurs = []


def verifier(cond, msg):
    print("   ", "ok    " if cond else "ÉCHEC ", msg)
    if not cond:
        erreurs.append(msg)


def types(r, gravite=None):
    return sorted(c["type"] for c in r["controles"] if gravite is None or c["gravite"] == gravite)


with tempfile.TemporaryDirectory() as tmp:
    print("=== bilan_enedis_reel_2026-11.csv (données réelles Enedis)")
    r = analyser_bilan.main([os.path.join(ICI, "bilan_enedis_reel_2026-11.csv"), "--sortie", tmp])
    verifier(r["pas_min"] == 15 and r["nb_pas"] == 768 and r["unite"] == "W", "pas 15 min, 768 pas, unité W")
    verifier(types(r, "majeure") == ["pas_manquants"], "une seule anomalie majeure : pas manquants")
    pm = [c for c in r["controles"] if c["type"] == "pas_manquants"][0]
    verifier(pm["debut"].startswith("2026-11-17T00:00") and pm["fin"].startswith("2026-11-17T23:45")
             and "96 pas" in pm["detail"], "journée du 17/11 entièrement absente (96 pas)")
    verifier("bilan_equilibre" in types(r, "info"), "bilan équilibré à chaque pas")
    verifier("colonne_nulle" in types(r, "mineure"), "temperature_normale_lissee à 0 signalée")
    j = {x["date"]: x for x in r["jours"]}
    verifier(j["2026-11-17"]["complet"] == "absent", "17/11 marqué absent dans les indicateurs")
    verifier(j["2026-11-16"]["energie_conso_mwh"] == 991755 and j["2026-11-16"]["pointe_conso_mw"] == 47692
             and j["2026-11-16"]["heure_pointe"] == "19:00", "16/11 : 991 755 MWh, pointe 47 692 MW à 19:00")
    verifier(j["2026-11-18"]["part_production_locale_pct"] == 42.3, "18/11 : 42,3 % de production locale")
    verifier(r["thermo"] is not None and r["thermo"]["r2"] < 0.5, "thermosensibilité jugée non exploitable (8 jours)")
    verifier(os.path.getsize(os.path.join(tmp, "rapport.html")) > 10000, "rapport HTML écrit")

    print("=== bilan_fictif_changement_heure.csv (pièges volontaires)")
    r = analyser_bilan.main([os.path.join(ICI, "bilan_fictif_changement_heure.csv"), "--sortie", tmp])
    verifier(r["pas_min"] == 30 and r["unite"] == "MW" and r["separateur"] == ";",
             "séparateur ; et virgule décimale lus, pas 30 min, unité MW")
    verifier(types(r, "majeure") == ["bilan_desequilibre", "horodate_en_double", "pas_manquants"],
             "majeures : bilan déséquilibré, doublon, pas manquants")
    verifier(types(r, "mineure") == ["jour_incomplet", "valeur_manquante"], "mineures : jour incomplet, valeur vide")
    j = {x["date"]: x for x in r["jours"]}
    verifier((j["2026-10-24"]["nb_pas"], j["2026-10-24"]["nb_pas_attendus"]) == (46, 48), "24/10 : 46 pas sur 48")
    verifier((j["2026-10-25"]["nb_pas"], j["2026-10-25"]["nb_pas_attendus"], j["2026-10-25"]["complet"]) == (50, 50, "oui"),
             "25/10 (passage à l'heure d'hiver) : 50 pas attendus, jour complet")
    verifier(j["2026-10-26"]["energie_pertes_mwh"] is None, "26/10 : énergie des pertes non calculée (valeur vide)")
    d = [c for c in r["controles"] if c["type"] == "bilan_desequilibre"][0]
    verifier(d["debut"].startswith("2026-10-26T18:00") and "50.0 MW" in d["detail"], "écart de 50 MW le 26/10 à 18:00")

print("\n" + ("Tout est conforme aux résultats attendus." if not erreurs else "%d écart(s)." % len(erreurs)))
sys.exit(1 if erreurs else 0)
