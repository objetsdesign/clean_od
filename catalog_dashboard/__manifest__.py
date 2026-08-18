# -*- coding: utf-8 -*-
{
    'name': "Catalogue Production - Dashboard",
    'version': '18.0.2.0.0',
    'category': 'Manufacturing',
    'summary': "Tableau de bord du catalogue produit : collections, fiches techniques, matières, production et stock.",
    'description': """
Catalogue Production - Dashboard
=================================
Module de gestion et de visualisation du catalogue produit (maroquinerie / textile).

Fonctionnalités :
------------------
* Collections de produits (une par gamme : MOKA, LORA, NOVA, RAYA, ELYA, SORA, SVEN, ERIIK...)
* Fiche produit reprenant exactement les champs du fichier Excel source :
  SKU, référence, description, dimensions, matières et couleurs (principale / secondaire / doublure),
  motif, accessoires, packaging individuel, production 1 & 2, dates de livraison, stock et coût de production.
* Statut de production calculé automatiquement (Réalisé / En cours / 2ème lancement / À planifier).
* Tableau de bord "Collections" avec indicateurs clés (références, stock total, coût moyen).
* Vue Kanban visuelle et attractive avec photo produit, pastilles couleur et badges de statut.
* Vue Liste fidèle à la structure du fichier Excel d'origine.
* Vues Pivot / Graphique pour l'analyse du stock, des coûts et de l'avancement de production.
* Galerie photo multi-images par référence produit.
* Coup de cœur (favoris) et alerte de stock faible avec seuil configurable.
* Fiche technique PDF imprimable par référence (à envoyer en production / fournisseur).
* Historique et messagerie (chatter) sur chaque référence produit.
""",
    'author': 'Clerieu Atelier',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/catalog_collection_data.xml',
        'data/catalog_product_data.xml',
        'report/catalog_product_report.xml',
        'views/catalog_collection_views.xml',
        'views/catalog_product_views.xml',
        'views/catalog_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'catalog_dashboard/static/src/scss/catalog_dashboard.scss',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
