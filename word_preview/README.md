# Aperçu Word (Odoo 18)

Affiche les fichiers .docx / .doc / .odt / .rtf dans la visionneuse d'Odoo
(comme un PDF). Conversion **sur votre serveur** avec LibreOffice : aucun
fichier n'est envoyé à un service externe. Le PDF est mis en cache.

## 1. Installer LibreOffice sur le serveur Odoo

Ubuntu / Debian :

    sudo apt update
    sudo apt install -y --no-install-recommends libreoffice-writer \
        fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea

(Carlito et Caladea remplacent Calibri et Cambria : mise en page fidèle.)

Docker : ajoutez la même ligne `apt-get install` dans votre Dockerfile.
Odoo.sh / Odoo Online : impossible d'installer LibreOffice, le module ne
fonctionnera pas.

Vérification : `soffice --version` (avec l'utilisateur qui lance Odoo).

## 2. Installer les modules

Copiez `word_preview` et `word_preview_documents` dans votre dossier
d'addons, redémarrez Odoo, puis Applications > Mettre à jour la liste >
installez « Aperçu Word ». `word_preview_documents` s'installe tout seul si
l'application Documents est présente.

## 3. Utilisation

- Cliquez sur un .docx (Documents, pièces jointes du chatter) : il s'ouvre
  dans la visionneuse. La première ouverture prend quelques secondes
  (conversion), les suivantes sont instantanées.
- Documents : sélectionnez un fichier > Action > « Aperçu Word » ouvre le
  PDF dans un nouvel onglet.
- Lien direct : `/word_preview/<id de la pièce jointe>`.

## Paramètres système (facultatifs)

- `word_preview.soffice_path` : chemin de soffice s'il n'est pas dans le PATH
- `word_preview.timeout` : durée max. de conversion en secondes (120)
- `word_preview.max_size_mb` : taille max. des fichiers convertis (30)
