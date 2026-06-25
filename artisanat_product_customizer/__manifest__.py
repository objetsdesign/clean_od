# -*- coding: utf-8 -*-
{
    'name': "Artisanat Product Customizer",
    'summary': "Personnalisation visuelle des produits façon Zakeke (texte, image, "
               "couleurs, polices) directement dans la fiche produit eCommerce.",
    'description': """
Artisanat Product Customizer
============================
Module de personnalisation produit (type Zakeke) pour les sites d'artisanat.

Fonctionnalités :
- Activation de la personnalisation par produit.
- Définition de zones personnalisables (front/back/...) avec coordonnées sur l'image.
- Éléments autorisés : texte, image client, cliparts, choix de couleur, police, taille.
- Configurateur visuel en temps réel sur la fiche produit (canvas Fabric.js).
- Calcul dynamique de l'impact prix.
- Sauvegarde du design (JSON + aperçu PNG) sur la ligne de commande.
- Aperçu et fichier d'impression visibles côté back-office (vente / fabrication).
    """,
    'author': "Votre Société",
    'website': "https://www.votre-site.tn",
    'category': 'Website/eCommerce',
    'version': '18.0.2.0.0',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
        'sale_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/customization_data.xml',
        'views/customization_area_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/website_templates.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            # Fabric.js est chargé dynamiquement (CDN) par le widget.
            # Pour l'auto-héberger : déposez fabric.min.js dans static/lib/fabric/
            # et décommentez la ligne ci-dessous.
            # 'artisanat_product_customizer/static/lib/fabric/fabric.min.js',
            'artisanat_product_customizer/static/src/css/customizer.css',
            'artisanat_product_customizer/static/src/js/product_customizer.js',
        ],
    },
    'images': ['static/description/banner.png'],
    'application': True,
    'installable': True,
}
