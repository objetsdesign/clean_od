# -*- coding: utf-8 -*-
{
    'name': 'Word dans Odoo (aperçu et modification)',
    'version': '18.0.3.0.0',
    'category': 'Productivity/Documents',
    'summary': "Aperçu et modification des fichiers Word dans Odoo, "
               "sans service externe",
    'description': """
Aperçu Word
===========
Les fichiers .docx s'ouvrent dans Odoo avec l'apparence de Word (pages
blanches, polices, tableaux, images, en-têtes / pieds de page), rendus
directement dans le navigateur : aucun fichier n'est envoyé à Google ou
Microsoft.
Bouton « Modifier dans Odoo » (comme « Ouvrir avec Odoo Feuille de calcul »
pour Excel) : le fichier s'ouvre dans l'éditeur de texte d'Odoo, puis
« Enregistrer dans le fichier Word » réécrit le fichier d'origine.
Les anciens formats (.doc, .odt, .rtf) sont affichés via une conversion
PDF. La modification et les anciens formats nécessitent LibreOffice sur le
serveur (voir README).
""",
    'author': 'VON ROSS',
    'license': 'LGPL-3',
    'depends': ['mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/word_document_security.xml',
        'views/word_document_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'word_preview/static/src/js/word_preview_patch.js',
            'word_preview/static/src/scss/word_editor.scss',
        ],
    },
    'installable': True,
    'application': False,
}
