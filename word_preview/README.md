# Aperçu Word (Odoo 18)

Affiche les fichiers Word dans Odoo **comme dans Word** : pages blanches,
polices, tableaux, images, en-têtes / pieds de page, zoom, impression et
téléchargement. Rendu dans le navigateur (bibliothèque docx-preview incluse
dans le module) : aucun fichier n'est envoyé à un service externe.

- .docx / .docm / .dotx : rendu « Word » direct, **sans rien installer**.
- .doc / .odt / .rtf (anciens formats) : conversion PDF par LibreOffice sur
  votre serveur (étape 1 ci-dessous, nécessaire seulement pour ces formats ;
  sert aussi de secours si un .docx ne peut pas être rendu).

## 1. (Facultatif) Installer LibreOffice sur le serveur Odoo

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

## Paramètres système (facultatifs)

- `word_preview.soffice_path` : chemin de soffice s'il n'est pas dans le PATH
- `word_preview.timeout` : durée max. de conversion en secondes (120)
- `word_preview.max_size_mb` : taille max. des fichiers convertis (30)

## Bibliothèques incluses

- docx-preview 0.4.1 (Apache-2.0) — static/lib/docx-preview.min.js
- JSZip 3.10.2 (MIT) — static/lib/jszip.min.js
