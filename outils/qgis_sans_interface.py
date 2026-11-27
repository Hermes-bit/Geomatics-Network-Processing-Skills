# -*- coding: utf-8 -*-
"""
Lance les algorithmes PyQGIS du dépôt sans ouvrir QGIS (en ligne de commande).

Utilisé par outils/tester_qgis.py et outils/rapport_anomalies.py. Sous Linux, lancez
ces scripts avec le Python de QGIS (souvent /usr/bin/python3). Sous Windows, ouvrez
l'« OSGeo4W Shell » et utilisez « python-qgis ». Sous macOS :
/Applications/QGIS.app/Contents/MacOS/bin/python3
"""

import importlib.util
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (  # noqa: E402
    QgsApplication,
    QgsProcessingAlgorithm,
    QgsProcessingProvider,
)

_app = None
_fournisseurs = []  # garder une référence Python, sinon le fournisseur est détruit


class FournisseurDepot(QgsProcessingProvider):
    """Fournisseur Traitements qui expose les scripts du dépôt (identifiant « depot »)."""

    def __init__(self, algos, ident="depot"):
        super().__init__()
        self._algos = algos
        self._id = ident

    def id(self):
        return self._id

    def name(self):
        return "Géomatique des réseaux (dépôt)"

    def loadAlgorithms(self):
        for a in self._algos:
            self.addAlgorithm(a)


def demarrer_qgis():
    """Démarre QGIS sans interface et initialise les Traitements (une seule fois)."""
    global _app
    if _app is not None:
        return _app
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    _app = QgsApplication([], False)
    _app.initQgis()
    for chemin in (os.path.join(QgsApplication.prefixPath(), "share", "qgis", "python", "plugins"),
                   "/usr/share/qgis/python/plugins"):
        if os.path.isdir(chemin) and chemin not in sys.path:
            sys.path.append(chemin)
    from processing.core.Processing import Processing
    Processing.initialize()
    return _app


def charger_algorithmes(*fichiers):
    """Charge les classes d'algorithme des fichiers .py donnés ; renvoie leurs identifiants (« depot:… »)."""
    demarrer_qgis()
    algos = []
    for f in fichiers:
        spec = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(f))[0], f)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, QgsProcessingAlgorithm)
                    and obj is not QgsProcessingAlgorithm and obj.__module__ == module.__name__):
                algos.append(obj())
    ident = "depot" if not _fournisseurs else "depot%d" % (len(_fournisseurs) + 1)
    fournisseur = FournisseurDepot(algos, ident)
    _fournisseurs.append(fournisseur)
    QgsApplication.processingRegistry().addProvider(fournisseur)
    return [ident + ":" + a.name() for a in algos]


def lancer(algo_id, parametres):
    """processing.run avec un retour d'informations affiché dans la console."""
    import processing
    from qgis.core import QgsProcessingFeedback

    class Retour(QgsProcessingFeedback):
        def pushInfo(self, info):
            print("   ", info)

        def pushWarning(self, info):
            print("    ATTENTION :", info)

        def reportError(self, error, fatalError=False):
            print("    ERREUR :", error)

    return processing.run(algo_id, parametres, feedback=Retour())
