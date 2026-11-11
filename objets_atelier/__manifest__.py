# -*- coding: utf-8 -*-

###############################################################################
{
    'name': "Gestion d'Atelier",
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': "Gestion des ordres de fabrication à l'atelier liés aux commandes clients",
    'description': """
        Module de gestion d'atelier :
        - Ordres d'atelier et lignes de matières premières avec calcul des coûts
        - Workflow complet avec contrôles et suivi dans le chatter
        - Génération automatique depuis les commandes clients
        - Droits d'accès Artisans / Responsables et règles multi-sociétés
        - Rapport PDF QWeb Fiche de fabrication et alertes automatiques de retard
    """,

    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'product',
        'sale_management',
    ],
    'data': [
        # 1. Sécurité (groupes et règles AVANT les droits d'accès CSV)
        'security/atelier_security.xml',
        'security/ir.model.access.csv',

        # 2. Données et actions planifiées
        'data/ir_cron_data.xml',

        # 3. Vues (les actions dans les vues doivent être chargées AVANT les menus)
        'views/atelier_ordre_views.xml',
        'views/sale_product_views.xml',
        'views/atelier_menus.xml',

        # 4. Rapports QWeb
        'report/atelier_ordre_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

