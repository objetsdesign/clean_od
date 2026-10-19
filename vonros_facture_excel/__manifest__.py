{
    'name': 'Von Ros - Facture Excel',
    'version': '18.0.2.0.1',
    'category': 'Accounting/Accounting',
    'summary': "Facture au design Von Ros Industry (identique au modèle Excel FA_10019)",
    'author': 'Von Ros Industry',
    'depends': ['account', 'sale'],
    'data': [
        'data/report_paperformat.xml',
        'views/res_partner_views.xml',
        'views/report_invoice_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
