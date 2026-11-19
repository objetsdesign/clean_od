# Aperçu Word (.docx) – clic dans Documents (Odoo 18)

Un simple clic sur un fichier Word dans **Documents** ouvre l'éditeur Word du
module `word_preview` dans un nouvel onglet.

Dépendances : `word_preview`, `documents`.

## Mise à jour depuis la version 1.x

Remplacer le dossier, redémarrer Odoo, puis Applications → « Aperçu Word » →
**Mettre à niveau**, puis **Ctrl + Maj + R** dans le navigateur.
Les anciens éléments (menu « Aperçu Word », action « Aperçu Word »,
visualiseur interne) sont supprimés automatiquement.

## Utilisation

* Clic simple sur un Word → éditeur Word.
* Ctrl / Maj + clic ou case à cocher → sélection normale.

## Diagnostic

* `https://votre-odoo/docx_preview/version` (sans `/odoo`) : version installée.
* Console du navigateur (F12) :
  `[Aperçu Word] clic Word actif – version 18.0.2.0.0`, puis
  `[Aperçu Word] ouverture de <nom>` à chaque clic.
