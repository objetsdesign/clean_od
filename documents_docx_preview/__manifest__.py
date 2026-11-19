{
    "name": "Aperçu Word – clic dans Documents (LibreOffice)",
    "version": "18.0.7.0.0",
    "summary": "Un clic sur un fichier Word dans Documents ouvre l'éditeur Word (LibreOffice)",
    "description": """
Clic Word dans Documents (Odoo 18)
==================================

Dans l'application Documents, un simple clic sur un fichier Word
(.docx, .doc, .odt, .rtf) ouvre l'éditeur Word dans un nouvel onglet :
ruban Accueil / Insertion / Tableau / Affichage, page A4,
« Enregistrer dans le fichier Word » qui réécrit le fichier d'origine.

Ctrl / Maj + clic et la case à cocher gardent la sélection normale.

Nécessite LibreOffice sur le serveur (sudo apt install libreoffice-writer).
    """,
    "category": "Productivity/Documents",
    "author": "VON ROSS",
    "license": "LGPL-3",
    "depends": ["mail", "documents"],
    "data": [
        "security/ir.model.access.csv",
        "security/word_document_security.xml",
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
