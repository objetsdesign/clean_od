# Aperçu Word (.docx) – Odoo 18

Affiche les fichiers `.docx` dans le visualiseur d'Odoo (application Documents,
pièces jointes du chatter). Le rendu est fait dans le navigateur avec
[docx-preview](https://github.com/VolodymyrBaydalka/docxjs) : pas de LibreOffice,
pas de service externe, les fichiers restent privés.

## Installation – serveur propre (On Premise)

1. Copier le dossier `documents_docx_preview` dans votre dossier d'addons
   personnalisés (voir `addons_path` dans `odoo.conf`).
2. Redémarrer Odoo : `sudo systemctl restart odoo`
3. Activer le mode développeur (Paramètres → Activer le mode développeur).
4. Applications → **Mettre à jour la liste des applications**.
5. Retirer le filtre « Applications », chercher **Aperçu Word**, cliquer **Activer**.

## Installation – Odoo.sh

1. Ajouter le dossier `documents_docx_preview` à la racine de votre dépôt GitHub.
2. `git add documents_docx_preview && git commit -m "Ajout aperçu docx" && git push`
   sur une branche **staging**.
3. Sur le build staging : Applications → Mettre à jour la liste → Activer.
4. Après test, fusionner vers la production et activer de la même façon.

## Vérification

* Documents → cliquer sur un fichier `.docx` → l'aperçu s'ouvre.
* Dans la console du navigateur (F12), le message
  `[documents_docx_preview] Aperçu .docx activé pour : ...` confirme que
  l'application Documents a bien été prise en compte.

## Limites

* L'ancien format `.doc` (Word 97-2003) n'est pas pris en charge.
* Mise en page proche de Word, mais pas identique pour les documents complexes.
* Les vignettes du kanban restent des icônes (seul l'aperçu au clic est ajouté).

## Licences

* Module : LGPL-3
* docx-preview : Apache-2.0 · JSZip : MIT / GPLv3 (voir `static/lib/*/LICENSE*`)
