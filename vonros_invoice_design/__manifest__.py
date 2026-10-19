{
    'name': 'Von Ros - Design Facture',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': "Facture au design Von Ros Industry (identique au modèle Excel FA_10019)",
    'author': 'Von Ros Industry',
    'depends': ['account', 'sale'],
    'data': [
        'data/report_paperformat.xml',
        'views/res_partner_views.xml',
        'views/report_invoice_templates.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'vonros_invoice_design/static/src/css/vonros_report.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
