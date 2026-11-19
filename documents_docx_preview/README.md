# Aperçu Word & PowerPoint – clic dans Documents · Odoo 18 (version 13.0, LibreOffice)

Une seule fonction : dans **Documents**, un **simple clic sur un fichier Word**
(.docx, .doc, .odt, .rtf) ouvre l'**éditeur Word** dans le **même onglet**
(bouton **Fermer** en haut à droite ou dans l'onglet Fichier : retour à Documents)
(ruban Accueil / Insertion / Tableau / Affichage, page A4).

* « Enregistrer dans le fichier Word » réécrit le fichier d'origine.
* Ctrl / Maj + clic ou case à cocher : sélection normale (pas d'éditeur).
* Les autres fichiers (PDF, Excel…) gardent le comportement normal.

## PowerPoint

Un **simple clic sur une présentation** (.pptx, .ppt, .odp, .pptm, .ppsx,
.pps, .potx) ouvre la **visionneuse de diapositives** dans le **même onglet**
(**Fermer** ramène à Documents, au même endroit) :

* conversion en PDF par LibreOffice, mise en cache (une seule conversion
  par version du fichier) ;
* bouton **Diaporama** (plein écran, flèches pour changer de diapositive,
  Échap pour quitter), **Télécharger** (fichier .pptx d'origine), **Fermer** ;
* bouton **Modifier les textes** (fichiers .pptx, utilisateurs ayant le droit
  de modifier le document) : voir ci-dessous.

### Éditeur PowerPoint

Chaque diapositive est affichée à gauche ; à droite, ses zones de texte
(titres, sous-titres, zones de texte, cellules de tableaux) :

* **texte** de chaque paragraphe ;
* **mise en forme** de chaque paragraphe : **G** (gras), *I* (italique),
  S (souligné), **taille** en points, **couleur** ;
* **animation d'entrée** de chaque zone : Aucune, Apparition, Fondu, Entrée
  par le bas — jouée au clic pendant le diaporama, dans l'ordre des zones.

Enregistrement :

* **Enregistrer** (ou Ctrl + S) réécrit le .pptx dans Documents : nouvelle
  version (l'ancienne reste dans « Gérer les versions »), miniatures mises à
  jour automatiquement.
* Tout ce qui n'est pas modifié (images, formes, mise en page, notes…) est
  recopié à l'identique.
* Si une diapositive contient déjà des animations avancées (emphase, sortie,
  trajectoires, sons…), elles sont **conservées** et le menu Animation de
  cette diapositive est grisé.
* Si le fichier a été modifié entre-temps par quelqu'un d'autre,
  l'enregistrement est refusé (pas d'écrasement).

Non pris en charge : déplacer / ajouter des formes ou des images, ajouter ou
supprimer des diapositives, mise en forme d'un seul mot, anciens formats
.ppt / .odp (lecture seule). Les animations ne s'affichent pas dans la
visionneuse (PDF) : elles sont jouées dans PowerPoint ou LibreOffice.

## Collabora Online (facultatif)

Si le connecteur officiel **`collabora_odoo`** (Collabora Productivity,
branche 18.0) est installé et que l'adresse du serveur Collabora est
renseignée dans ses paramètres, le clic sur un Word ou un PowerPoint ouvre
**Collabora Online** (édition complète : couleurs, tailles, formes, images,
animations, diapositives). Mode modification si l'utilisateur a le droit de
modifier le document, sinon lecture.

Sans Collabora, les éditeurs LibreOffice de ce module restent utilisés.
Pour revenir à ces éditeurs sans désinstaller Collabora : paramètre système
`docx_preview.use_collabora` = `False`.
La visionneuse de diapositives reste accessible avec `/slides_preview/<id>?viewer=1`.

## Prérequis : LibreOffice sur le serveur

`libreoffice-impress` est nécessaire pour les PowerPoint.

    sudo apt install libreoffice-writer libreoffice-impress
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
* `[Aperçu Word] clic Word actif – version 18.0.13.0.0` → code chargé ;
* `[Aperçu Word] ouverture de <nom>` → clic pris en compte.

## Bibliothèques incluses

* docx-preview 0.4.1 (Apache-2.0) et JSZip 3.10.2 (MIT / GPLv3) — static/lib/
