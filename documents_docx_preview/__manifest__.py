{
    "name": "Aperçu Word (.docx) – clic dans Documents",
    "version": "18.0.5.0.0",
    "summary": "Un clic sur un fichier .docx dans Documents ouvre l'éditeur Word",
    "description": """
Clic Word dans Documents (Odoo 18)
==================================

Dans l'application Documents, un simple clic sur un fichier .docx ouvre
l'éditeur Word (SuperDoc) dans un nouvel onglet :

* mise en page Word fidèle, barre d'outils de mise en forme ;
* « Enregistrer » (ou Ctrl + S) réécrit le fichier dans Documents
  (l'ancienne version reste dans « Gérer les versions ») ;
* lecture seule pour les utilisateurs sans droit de modification ;
* tout se passe dans le navigateur : ni LibreOffice ni service externe,
  aucune donnée envoyée à l'extérieur.

Ctrl / Maj + clic et la case à cocher gardent la sélection normale.

Licence AGPL-3 : inclut l'éditeur SuperDoc 1.45 (AGPL-3.0),
voir static/lib/superdoc/LICENSE.
    """,
    "category": "Productivity/Documents",
    "author": "VON ROSS",
    "license": "AGPL-3",
    "depends": ["documents"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "documents_docx_preview/static/src/js/documents_word_click.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
