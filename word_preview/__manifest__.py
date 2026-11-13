# -*- coding: utf-8 -*-
{
    'name': 'Aperçu Word (DOCX / DOC / ODT / RTF)',
    'version': '18.0.1.1.0',
    'category': 'Productivity/Documents',
    'summary': "Affiche les fichiers Word dans Odoo comme dans Word "
               "(pages, mise en page), sans service externe",
    'description': """
Aperçu Word
===========
Les fichiers .docx s'ouvrent dans Odoo avec l'apparence de Word (pages
blanches, polices, tableaux, images, en-têtes / pieds de page), rendus
directement dans le navigateur : aucun fichier n'est envoyé à Google ou
Microsoft.
Les anciens formats (.doc, .odt, .rtf) sont affichés via une conversion
PDF faite sur votre serveur par LibreOffice (facultatif, voir README).
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
