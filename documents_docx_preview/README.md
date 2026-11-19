# Aperçu Word (.docx) – clic dans Documents (Odoo 18)

Un simple clic sur un fichier Word dans **Documents** ouvre l'éditeur Word du
module `word_preview` dans un nouvel onglet.

Dépendances : `word_preview`, `documents`.

## Mise à jour depuis la version 1.x

Remplacer le dossier, redémarrer Odoo, puis Applications → « Aperçu Word » →
**Mettre à niveau**, puis **Ctrl + Maj + R** dans le navigateur.
L'ancien bouton « Ouvrir dans Word », l'action « Aperçu Word » du menu Action et le
visualiseur interne sont supprimés automatiquement.

## Utilisation

* Documents → menu du haut **Aperçu Word** → bouton **Aperçu** sur la ligne
  → l'éditeur Word s'ouvre dans un nouvel onglet.

* Clic simple sur un Word → éditeur Word.
* Ctrl / Maj + clic ou case à cocher → sélection normale.

## Diagnostic

* `https://votre-odoo/docx_preview/version` (sans `/odoo`) : version installée.
* Console du navigateur (F12) :
  `[Aperçu Word] clic Word actif – version 18.0.2.1.0`, puis
  `[Aperçu Word] ouverture de <nom>` à chaque clic.
