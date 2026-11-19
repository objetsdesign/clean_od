{
    "name": "Aperçu Word (.docx) – Documents & pièces jointes",
    "version": "18.0.1.4.0",
    "summary": "Affiche les fichiers Word (.docx) dans le visualiseur d'Odoo, sans téléchargement",
    "description": """
Aperçu des fichiers Word (.docx) dans Odoo 18
=============================================

* Ajoute le format .docx au visualiseur de fichiers d'Odoo (application Documents,
  pièces jointes du chatter, champs fichiers).
* Le rendu se fait entièrement dans le navigateur (bibliothèque docx-preview) :
  aucun LibreOffice, aucun service externe, aucune URL publique.
  Les fichiers restent privés.

Limites : l'ancien format .doc (Word 97-2003) n'est pas pris en charge, et la mise en
page peut différer légèrement de Word pour les documents complexes.
    """,
    "category": "Productivity/Documents",
    "author": "Interne",
    "license": "LGPL-3",
    "depends": ["web", "mail", "documents"],
    "data": [
        "data/server_actions.xml",
        "views/docx_preview_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "documents_docx_preview/static/src/js/docx_file_model_patch.js",
            "documents_docx_preview/static/src/js/documents_docx_click.js",
            "documents_docx_preview/static/src/xml/file_viewer.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
