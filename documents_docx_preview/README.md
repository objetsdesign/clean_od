# Aperçu Word – clic dans Documents · Odoo 18 (version 7.0, LibreOffice)

Une seule fonction : dans **Documents**, un **simple clic sur un fichier Word**
(.docx, .doc, .odt, .rtf) ouvre l'**éditeur Word** dans un nouvel onglet
(ruban Accueil / Insertion / Tableau / Affichage, page A4).

* « Enregistrer dans le fichier Word » réécrit le fichier d'origine.
* Ctrl / Maj + clic ou case à cocher : sélection normale (pas d'éditeur).
* Les autres fichiers (PDF, Excel…) gardent le comportement normal.

## Prérequis : LibreOffice sur le serveur

    sudo apt install libreoffice-writer
    soffice --version   # avec l'utilisateur qui lance Odoo

## Mise à jour depuis une version précédente

Remplacer le dossier, redémarrer Odoo, puis Applications → « Aperçu Word » →
**Mettre à niveau**, puis **Ctrl + Maj + R** dans le navigateur.

## Limites de l'éditeur

La conversion Word ⇄ éditeur garde texte, mise en forme, titres, listes,
tableaux et images. En-têtes / pieds de page, zones de texte, colonnes,
sauts de section, suivi des modifications et commentaires peuvent être
perdus ou simplifiés.

## Paramètres système (facultatifs)

* `word_preview.soffice_path` : chemin de soffice s'il n'est pas dans le PATH
* `word_preview.timeout` : durée max. de conversion en secondes (120)
* `word_preview.max_size_mb` : taille max. des fichiers convertis (30)

## Diagnostic

Console du navigateur (F12) :
* `[Aperçu Word] clic Word actif – version 18.0.7.0.0` → code chargé ;
* `[Aperçu Word] ouverture de <nom>` → clic pris en compte.

## Bibliothèques incluses

* docx-preview 0.4.1 (Apache-2.0) et JSZip 3.10.2 (MIT / GPLv3) — static/lib/
