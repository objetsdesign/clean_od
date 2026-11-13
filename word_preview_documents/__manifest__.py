# -*- coding: utf-8 -*-
{
    'name': 'Aperçu Word - Documents',
    'version': '18.0.2.0.0',
    'category': 'Productivity/Documents',
    'summary': "Ajoute « Aperçu Word » et « Modifier dans Odoo (Word) » aux actions de Documents",
    'author': 'VON ROSS',
    'license': 'LGPL-3',
    'depends': ['word_preview', 'documents'],
    'data': [
        'data/ir_actions_server.xml',
    ],
    'auto_install': True,
    'installable': True,
}
