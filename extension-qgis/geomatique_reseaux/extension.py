# -*- coding: utf-8 -*-
"""Extension QGIS : fournisseur Traitements, bouton et menu « Géomatique des réseaux »."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .fournisseur import FournisseurGeomatiqueReseaux

ICI = os.path.dirname(os.path.abspath(__file__))
MENU = "&Géomatique des réseaux"
# (identifiant de l'algorithme, libellé du menu, dans la barre d'outils ?)
ENTREES = (
    ("analyse_impact_chantier", "Analyse d'impact d'un chantier…", True),
    ("proximite_dt_dict", "Proximité DT-DICT…", False),
    ("referencement_pk_ferroviaire", "Référencement PK ferroviaire…", False),
    ("controle_topologie_reseau", "Contrôle de topologie du réseau…", False),
)


class ExtensionGeomatiqueReseaux:
    def __init__(self, iface):
        self.iface = iface
        self.fournisseur = None
        self.actions = []
        self.barre = None

    def initProcessing(self):
        self.fournisseur = FournisseurGeomatiqueReseaux()
        QgsApplication.processingRegistry().addProvider(self.fournisseur)

    def initGui(self):
        self.initProcessing()
        icone = QIcon(os.path.join(ICI, "icone.svg"))
        self.barre = self.iface.addToolBar("Géomatique des réseaux")
        self.barre.setObjectName("GeomatiqueReseaux")
        for ident, libelle, barre in ENTREES:
            if not QgsApplication.processingRegistry().algorithmById("geomatique_reseaux:" + ident):
                continue
            action = QAction(icone, libelle, self.iface.mainWindow())
            action.triggered.connect(lambda _=False, i=ident: self.ouvrir(i))
            self.iface.addPluginToMenu(MENU, action)
            if barre:
                self.barre.addAction(action)
            self.actions.append(action)

    def ouvrir(self, ident):
        import processing
        processing.execAlgorithmDialog("geomatique_reseaux:" + ident)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        self.actions = []
        if self.barre is not None:
            self.barre.deleteLater()
            self.barre = None
        if self.fournisseur is not None:
            QgsApplication.processingRegistry().removeProvider(self.fournisseur)
            self.fournisseur = None
