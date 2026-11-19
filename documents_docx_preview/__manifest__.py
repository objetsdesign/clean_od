{
    "name": "Aperçu Word (.docx) – Documents",
    "version": "18.0.3.1.0",
    "summary": "Aperçu et éditeur Word dans Documents : bouton Aperçu, clic sur un Word, "
               "« Modifier dans Odoo (Word) »",
    "description": """
Aperçu et éditeur Word dans Documents (Odoo 18)
===============================================

Module unique (remplace word_preview et word_preview_documents) :

* Éditeur Word dans Odoo (ruban Accueil / Insertion / Tableau / Affichage,
  page A4), avec « Enregistrer dans le fichier Word ».
* Documents → menu « Aperçu Word » : liste des fichiers Word, bouton
  « Aperçu » qui ouvre l'éditeur Word.
* Documents → clic simple sur un fichier Word : ouvre l'éditeur Word.
* Documents → « ⚙ Action » : « Aperçu Word » et « Modifier dans Odoo (Word) ».
* Documents → menu « Documents Word » : copies de travail en cours.
* Visualiseur d'Odoo : les fichiers Word deviennent visualisables.

La modification et les anciens formats (.doc, .odt, .rtf) nécessitent
LibreOffice sur le serveur (sudo apt install libreoffice-writer).
    """,
    "category": "Productivity/Documents",
    "author": "VON ROSS",
    "license": "LGPL-3",
    "depends": ["mail", "documents"],
    "data": [
        "security/ir.model.access.csv",
        "security/word_document_security.xml",
        "views/word_document_views.xml",
        "views/docx_preview_views.xml",
        "views/documents_actions.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "documents_docx_preview/static/src/js/word_preview_patch.js",
            "documents_docx_preview/static/src/scss/word_editor.scss",
            "documents_docx_preview/static/src/js/documents_word_click.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
