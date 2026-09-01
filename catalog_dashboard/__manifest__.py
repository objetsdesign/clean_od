# -*- coding: utf-8 -*-
{
    'name': "Catalogue Production - Dashboard",
    'version': '18.0.3.0.0',
    'category': 'Manufacturing',
    'summary': "Pilotage produit Objets Design : hiérarchie Projet/Axe/Marque/Collection/Modèle/Variante, cycle de développement et indicateurs Direction.",
    'description': """
Catalogue Production - Dashboard
=================================
Module de pilotage du catalogue produit multi-axes (Objets Design).

Architecture :
--------------
Projet > Axe (Luminaire, Bougie, Parfum d'ambiance, Textile, Bagagerie, B2B...) >
Marque > Collection > Modèle > Variante / référence SKU.

Fonctionnalités :
------------------
* Hiérarchie complète Projet / Axe / Marque / Collection / Modèle / Variante.
* Cycle de développement produit en 11 étapes (Idée → Produit archivé), indépendant du statut du stock.
* Statut du stock distinct (rupture / faible / disponible) et distinct du statut de développement.
* Coût cible vs coût de production réel (interne), avec écart calculé et indicateur "coût validé".
* Fiche technique reprenant les champs matières, couleurs, accessoires, packaging.
* Fiche technique jugée "complète" automatiquement selon les champs clés renseignés.
* Statut de préparation e-commerce (Shopify / marketplaces) et suivi des documents de conformité.
* Tableau de bord Direction : produits par étape, produits en retard, prototypes/BAT à valider,
  fiches techniques incomplètes, produits sans coût validé, stock sous seuil, écarts de coût,
  préparation Shopify/marketplaces, documents de conformité manquants.
* Vue Kanban visuelle avec photo produit, pastilles couleur et badges de statut (production + stock).
* Vues Pivot / Graphique pour l'analyse du stock, des coûts et de l'avancement.
* Galerie photo multi-images par référence produit.
* Coup de cœur (favoris) et alerte de stock faible avec seuil configurable.
* Fiche technique PDF imprimable par référence.
* Historique et messagerie (chatter) sur chaque référence produit.
""",
    'author': 'Clerieu Atelier',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail', 'product', 'sale', 'purchase', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/catalog_project_data.xml',
        'data/catalog_odoo_import_data.xml',
        'data/catalog_axe_data.xml',
        'data/catalog_brand_data.xml',
        'data/catalog_collection_data.xml',
        'data/catalog_model_data.xml',
        'data/catalog_product_data.xml',
        'data/catalog_cron_data.xml',
        'report/catalog_product_report.xml',
        'views/catalog_project_views.xml',
        'views/catalog_axe_views.xml',
        'views/catalog_brand_views.xml',
        'views/catalog_collection_views.xml',
        'views/catalog_model_views.xml',
        'views/catalog_product_views.xml',
        'views/product_template_views.xml',
        'views/catalog_direction_dashboard_views.xml',
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
    'post_init_hook': 'post_init_hook',
}
