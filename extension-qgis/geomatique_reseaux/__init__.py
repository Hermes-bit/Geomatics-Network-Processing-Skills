# -*- coding: utf-8 -*-
"""Extension QGIS « Géomatique des réseaux »."""


def classFactory(iface):  # appelé par QGIS au chargement de l'extension
    from .extension import ExtensionGeomatiqueReseaux
    return ExtensionGeomatiqueReseaux(iface)
