{
    "name": "Timesheet Employee Objetsdesign",
    'version': '1.0',
    'summary': 'This module transforms Odoo into a highly customized CRM + project management + timesheet tool for Objetsdesign, featuring a 360° customer profile, synchronized collaborative timesheets, and an enriched CRM pipeline with margin calculation and direct actions.',
    'author': 'VON ROSS',
    'depends': ['sale', 'base', 'web', 'mail', 'stock', 'crm', 'timesheet_grid', 'hr_timesheet', 'board', 'project',
                'analytic', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/timesheet.xml',
        'views/account_move_inherit.xml',
        'views/sector_activity_view.xml',
        'views/res_partner.xml',
        'views/crm_lead.xml',

    ],
    'assets': {
        'web.assets_backend': [
            'timesheet_objetsdesign_custom/static/src/scss/style.scss',
            'timesheet_objetsdesign_custom/static/src/xml/create_hide.xml',
        ],
        'web.assets_frontend': [
            'timesheet_objetsdesign_custom/static/src/scss/front.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
