# -*- coding: utf-8 -*-
{
    'name': "Suivi Devis & Commandes - B2B / Fund Raising / Asie",
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': "Suivi des devis et commandes B2B, Fund Raising et Asie avec tableau de bord",
    'description': """
Suivi Devis & Commandes — B2B / Fund Raising / Asie
====================================================
Module de reprise du fichier Excel "Suivi_Devis_Commandes_OD - B2B FUND ASIE" :

* Onglets Devis / Commandes pour chacune des 3 activités (B2B Classique, Fund Raising, Asie)
* Classification "Asie" portée par un modèle dédié (sale.order.sky), qui ne modifie
  jamais le devis/commande sale.order d'origine
* Lien Devis <-> Commande
* Suivi des relances, statuts, probabilité de conversion
* Suivi production, expédition, livraison, acompte / solde
* Tableau de bord avec KPIs par activité et vue consolidée
* Guide d'utilisation intégré

Développé pour Groupe Lassaye - Objets Design.
    """,
    'author': "Groupe Lassaye",
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale'],
    'data': [
        'security/b2fa_security.xml',
        'security/ir.model.access.csv',
        'data/b2fa_data.xml',
        'views/b2fa_quote_views.xml',
        'views/b2fa_order_views.xml',
        'views/b2fa_dashboard_views.xml',
        'views/sale_order_views.xml',
        'views/sale_order_sky_views.xml',
        'wizard/b2fa_guide_views.xml',
        'wizard/b2fa_import_views.xml',
        'wizard/b2fa_sync_views.xml',
        'views/b2fa_menus.xml',
    ],
    'demo': [
        'data/b2fa_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'web/static/lib/Chart/Chart.js',
            'b2b_fund_asie_tracking/static/src/js/dashboard.js',
            'b2b_fund_asie_tracking/static/src/xml/dashboard.xml',
            'b2b_fund_asie_tracking/static/src/scss/dashboard.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
