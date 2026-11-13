# Word dans Odoo : aperçu et modification (Odoo 18)

Affiche les fichiers Word dans Odoo **comme dans Word** : pages blanches,
polices, tableaux, images, en-têtes / pieds de page, zoom, impression et
téléchargement. Rendu dans le navigateur (bibliothèque docx-preview incluse
dans le module) : aucun fichier n'est envoyé à un service externe.

- .docx / .docm / .dotx : rendu « Word » direct, **sans rien installer**.
- .doc / .odt / .rtf (anciens formats) : aperçu PDF par LibreOffice.
- **Modifier dans Odoo** (comme « Ouvrir avec Odoo Feuille de calcul » pour
  Excel) : le fichier s'ouvre dans l'éditeur de texte d'Odoo (page A4,
  gras, couleurs, polices, titres, listes, tableaux, images…), puis
  « Enregistrer dans le fichier Word » réécrit le fichier d'origine, ou
  « Télécharger .docx ». Nécessite LibreOffice (étape 1).

## 1. Installer LibreOffice sur le serveur Odoo (pour « Modifier » et les .doc)

Ubuntu / Debian :

    sudo apt update
    sudo apt install -y --no-install-recommends libreoffice-writer \
        fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea

(Carlito et Caladea remplacent Calibri et Cambria : mise en page fidèle.)

Docker : ajoutez la même ligne `apt-get install` dans votre Dockerfile.
Odoo.sh / Odoo Online : impossible d'installer LibreOffice ; seuls les .docx
seront affichés.

Vérification : `soffice --version` (avec l'utilisateur qui lance Odoo).

## 2. Installer les modules

Copiez `word_preview` et `word_preview_documents` dans votre dossier
d'addons, redémarrez Odoo, puis Applications > Mettre à jour la liste >
installez « Aperçu Word ». `word_preview_documents` s'installe tout seul si
l'application Documents est présente.

## 3. Utilisation

- Cliquez sur un .docx (Documents, pièces jointes du chatter) : il s'ouvre
  dans la visionneuse, avec l'apparence de Word.
- Documents : activez « Aperçu Word » dans l'engrenage du dossier >
  Actions on Select, puis sélectionnez un fichier > Action > « Aperçu Word »
  (ouvre l'aperçu dans un nouvel onglet).
- Lien direct : `/word_preview/<id de la pièce jointe>/view`
  (`/word_preview/<id>` donne la version PDF).

## Modifier un document Word dans Odoo (éditeur « Word »)

Un clic sur un .docx (Documents, chatter…) ouvre l'éditeur « Word » d'Odoo :
ruban Fichier / Accueil / Insertion / Tableau / Affichage (police, taille,
gras, italique, souligné, barré, indice, exposant, couleurs, surlignage,
puces, numérotation, retraits, alignements, interligne, trame, styles
Titre 1-3, rechercher / remplacer, saut de page, tableaux et lignes /
colonnes, images, liens, symboles, date, zoom, impression / PDF), page A4,
barre d'état (pages, mots, zoom), raccourcis Ctrl+S, Ctrl+G, Ctrl+E…
« Enregistrer » réécrit le fichier .docx d'origine ; brouillon auto toutes
les minutes. Lien direct : /word_editor/sheet/<id de la pièce jointe>.

- Depuis l'aperçu : bouton blanc « Modifier dans Odoo » dans la barre bleue.
- Depuis Documents : activez « Modifier dans Odoo (Word) » dans l'engrenage
  du dossier > Actions on Select, puis sélectionnez le fichier > Action.
- Menu « Documents Word » : toutes vos copies de travail.

Chaque utilisateur a sa propre copie de travail (enregistrée
automatiquement) ; « Enregistrer dans le fichier Word » met à jour le fichier
d'origine (droit d'écriture sur ce fichier requis).

Limites : la conversion Word ⇄ éditeur Odoo garde texte, mise en forme,
titres, listes, tableaux et images, mais pas tout : en-têtes / pieds de page,
zones de texte, colonnes, sauts de section, suivi des modifications et
commentaires Word peuvent être perdus ou simplifiés. Pour une édition 100 %
fidèle, utilisez ONLYOFFICE.

## Paramètres système (facultatifs)

- `word_preview.soffice_path` : chemin de soffice s'il n'est pas dans le PATH
- `word_preview.timeout` : durée max. de conversion en secondes (120)
- `word_preview.max_size_mb` : taille max. des fichiers convertis (30)

## Bibliothèques incluses

- docx-preview 0.4.1 (Apache-2.0) — static/lib/docx-preview.min.js
- JSZip 3.10.2 (MIT) — static/lib/jszip.min.js
