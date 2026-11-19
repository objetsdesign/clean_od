# Aperçu Word (.docx) – clic dans Documents · Odoo 18 (version 6.0)

Une seule fonction : dans **Documents**, un **simple clic sur un fichier .docx**
ouvre l'**éditeur Word** (docx-editor) dans un nouvel onglet :
interface en français (Fichier, Format, Insérer, Révision, Aide), styles,
règles, tableaux, images, mise en page Word.

* **Enregistrer** (ou Ctrl + S) réécrit le fichier dans Documents ;
  l'ancienne version reste dans « Gérer les versions ».
* **Télécharger** : télécharge le document tel qu'il est à l'écran.
* Utilisateurs sans droit de modification : lecture seule.
* Ctrl / Maj + clic ou case à cocher : sélection normale (pas d'éditeur).
* Les autres fichiers (PDF, Excel, .doc…) gardent le comportement normal.
* Rien n'est envoyé à l'extérieur ; LibreOffice n'est pas nécessaire.

Dépendance : `documents` (Odoo 18 Enterprise).

## Mise à jour depuis une version précédente

Remplacer le dossier, redémarrer Odoo, puis Applications → « Aperçu Word » →
**Mettre à niveau**, puis **Ctrl + Maj + R** dans le navigateur.
Les menus « Aperçu Word » / « Documents Word », les actions du menu ⚙ Action
et l'ancien éditeur sont supprimés automatiquement.

## Diagnostic

Console du navigateur (F12) :
* `[Aperçu Word] clic Word actif – version 18.0.6.0.0` → code chargé ;
* `[Aperçu Word] ouverture de <nom>` → clic pris en compte.

## Licence

LGPL-3. Inclut docx-editor 2.39.0 (Apache-2.0) et React 18 (MIT) —
static/lib/docx-editor/licenses/. À l'enregistrement, docx-editor conserve
tel quel tout le contenu non modifié du fichier.
