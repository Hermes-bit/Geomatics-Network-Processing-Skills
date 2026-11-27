# -*- coding: utf-8 -*-
"""Fournisseur Traitements : charge les algorithmes copiés des dossiers qgis/ des skills."""

import importlib.util
import os

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingAlgorithm, QgsProcessingProvider

ICI = os.path.dirname(os.path.abspath(__file__))
DOSSIER = os.path.join(ICI, "algorithmes")


def charger_classes():
    """Classes d'algorithme des fichiers .py de algorithmes/ (copiés par outils/empaqueter_extension.sh)."""
    classes = []
    for nom in sorted(os.listdir(DOSSIER)) if os.path.isdir(DOSSIER) else []:
        if not nom.endswith(".py") or nom.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location("geomatique_reseaux_algo_" + nom[:-3], os.path.join(DOSSIER, nom))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, QgsProcessingAlgorithm)
                    and obj is not QgsProcessingAlgorithm and obj.__module__ == module.__name__):
                classes.append(obj)
    return classes


class FournisseurGeomatiqueReseaux(QgsProcessingProvider):
    def __init__(self):
        super().__init__()
        self._classes = charger_classes()

    def id(self):
        return "geomatique_reseaux"

    def name(self):
        return "Géomatique des réseaux"

    def icon(self):
        return QIcon(os.path.join(ICI, "icone.svg"))

    def loadAlgorithms(self):
        for c in self._classes:
            self.addAlgorithm(c())
