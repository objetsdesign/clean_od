{
    'name': 'Von Ros - Design Facture',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Facture au design Von Ros Industry (uniquement pour la société Von Ros)",
    'author': 'Von Ros Industry',
    'depends': ['account', 'sale'],
    'data': [
        'views/res_partner_views.xml',
        'views/report_invoice_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
