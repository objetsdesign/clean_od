{
    'name': 'Newsletter CRM Direct (Odoo 18)',
    'version': '1.1',
    'depends': [
        'website_mass_mailing',
        'crm', 'event', 'sale',
        'auth_signup', 'portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/newslettre_new.xml',
        'views/registration_event.xml',
        'views/template_mail.xml',
        'views/sale_order_filter.xml',
        'data/mail_purchase.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'newsletter_crm_direct/static/src/js/news_lettre.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
