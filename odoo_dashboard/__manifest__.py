# -*- coding: utf-8 -*-
{
    'name': 'Dashboard Global - Vue d\'ensemble',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Dashboards',
    'summary': "Vue globale simple sur l'activité de tous les modules Odoo installés",
    'description': """
Dashboard Global
=================
Ce module ajoute un tableau de bord centralisé (une seule page) qui donne une
vue d'ensemble sur l'activité des principaux modules Odoo installés :

- Ventes (sale.order)
- Achats (purchase.order)
- Facturation (account.move)
- Inventaire / Stock (stock.picking)
- Fabrication (mrp.production)
- Point de vente (pos.order)
- CRM / Opportunités (crm.lead)
- Projets (project.task)
- Ressources Humaines (hr.employee)
- Support / Helpdesk (helpdesk.ticket)

Chaque bloc affiche le nombre d'enregistrements et ouvre en un clic la vue
standard du module correspondant. Si un module n'est pas installé, le
bloc affiche 0 et un message d'information s'affiche au clic (aucune erreur).

Aucune dépendance forte : le module fonctionne même si seuls "base" et "web"
sont installés, et s'enrichit automatiquement quand d'autres modules Odoo
sont ajoutés.
    """,
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/dashboard_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_dashboard/static/src/scss/dashboard.scss',
            'odoo_dashboard/static/src/js/dashboard.js',
            'odoo_dashboard/static/src/xml/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
