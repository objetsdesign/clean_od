# Aperçu Word (.docx) – Documents · Odoo 18 (version 3.0)

Module **unique** : aperçu et éditeur Word dans Documents.
Il **remplace** `word_preview` et `word_preview_documents` (à désinstaller).

## Fonctions

* **Documents → menu du haut « Aperçu Word »** : liste des fichiers Word,
  bouton **Aperçu** → éditeur Word dans un nouvel onglet.
* **Documents → clic simple** sur un fichier Word → éditeur Word.
  (Ctrl / Maj + clic ou case à cocher = sélection normale.)
* **Documents → ⚙ Action** : « Aperçu Word » et « Modifier dans Odoo (Word) ».
  ⚠️ Dans Documents 18, ces actions doivent être activées par dossier :
  engrenage ⚙ du dossier → *Actions on Select* → cocher les deux actions.
* **Documents → menu « Documents Word »** : copies de travail de l'éditeur.
* Éditeur Word : ruban Accueil / Insertion / Tableau / Affichage, page A4,
  « Enregistrer dans le fichier Word » réécrit le fichier d'origine.

## Prérequis : LibreOffice sur le serveur

Nécessaire pour l'éditeur et les anciens formats (.doc, .odt, .rtf) :

    sudo apt install libreoffice-writer
    soffice --version   # avec l'utilisateur qui lance Odoo

## Installation (migration depuis word_preview)

1. Applications → **désinstaller `word_preview`** (cela désinstalle aussi
   `word_preview_documents` et l'ancien `documents_docx_preview`).
   Les copies de travail en cours de l'éditeur sont supprimées : enregistrez
   d'abord vos modifications dans les fichiers Word. Les fichiers de
   Documents ne sont pas touchés.
2. Sur le serveur : supprimer (ou déplacer hors du dossier d'addons) les
   dossiers `word_preview` et `word_preview_documents`, puis remplacer
   `documents_docx_preview` par cette version.
3. Redémarrer Odoo.
4. Applications → **Mettre à jour la liste des applications** → chercher
   « Aperçu Word » → **Activer**.
5. Navigateur : **Ctrl + Maj + R**.

## Liens directs

* `/docx_preview/version` – version installée (contrôle)
* `/docx_preview/open/<id document>` – éditeur Word d'un document de Documents
* `/word_editor/sheet/<id pièce jointe>` – éditeur Word
* `/word_preview/<id pièce jointe>/view` – aperçu (PDF : `/word_preview/<id>`)

## Limites de l'éditeur

La conversion Word ⇄ éditeur garde texte, mise en forme, titres, listes,
tableaux et images. En-têtes / pieds de page, zones de texte, colonnes,
sauts de section, suivi des modifications et commentaires peuvent être
perdus ou simplifiés. Pour une édition 100 % fidèle : ONLYOFFICE.

## Paramètres système (facultatifs)

* `word_preview.soffice_path` : chemin de soffice s'il n'est pas dans le PATH
* `word_preview.timeout` : durée max. de conversion en secondes (120)
* `word_preview.max_size_mb` : taille max. des fichiers convertis (30)

## Bibliothèques incluses

* docx-preview 0.4.1 (Apache-2.0) — static/lib/docx-preview.min.js
* JSZip 3.10.2 (MIT / GPLv3) — static/lib/jszip.min.js
