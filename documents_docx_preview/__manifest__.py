{
    "name": "Aperçu Word (.docx) – Documents",
    "version": "18.0.2.1.0",
    "summary": "Menu « Aperçu Word » dans Documents : le bouton Aperçu ouvre l'éditeur Word (module word_preview)",
    "description": """
Clic Word dans Documents
========================

* Menu « Aperçu Word » dans Documents : liste des fichiers Word, bouton
  « Aperçu » qui ouvre l'éditeur Word du module word_preview.
* Dans l'application Documents, un simple clic sur un fichier Word
  (.docx, .doc, .odt, .rtf) ouvre l'éditeur Word du module word_preview,
  comme « Action > Modifier dans Odoo (Word) ».
* Ctrl / Maj + clic et la case à cocher gardent la sélection normale.
* Les droits de lecture sur le document sont vérifiés côté serveur.
    """,
    "category": "Productivity/Documents",
    "author": "VON ROSS",
    "license": "LGPL-3",
    "depends": ["word_preview", "documents"],
    "data": [
        "views/docx_preview_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "documents_docx_preview/static/src/js/documents_word_click.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
