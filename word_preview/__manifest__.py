# -*- coding: utf-8 -*-
{
    'name': 'Aperçu Word (DOCX / DOC / ODT / RTF)',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Documents',
    'summary': "Affiche les fichiers Word dans la visionneuse d'Odoo "
               "(conversion PDF locale avec LibreOffice, sans service externe)",
    'description': """
Aperçu Word
===========
Les fichiers .docx / .doc / .odt / .rtf s'ouvrent dans la visionneuse
d'Odoo, comme un PDF. La conversion est faite sur votre serveur par
LibreOffice : aucun fichier n'est envoyé à Google ou Microsoft.
Le PDF généré est mis en cache (une seule conversion par version du fichier).

Prérequis serveur : LibreOffice (voir README).
""",
    'author': 'VON ROSS',
    'license': 'LGPL-3',
    'depends': ['mail'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'word_preview/static/src/js/word_preview_patch.js',
        ],
    },
    'installable': True,
    'application': False,
}
