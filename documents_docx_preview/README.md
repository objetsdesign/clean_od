# Aperçu Word (.docx) – clic dans Documents · Odoo 18 (version 5.0)

Une seule fonction : dans **Documents**, un **simple clic sur un fichier .docx**
ouvre l'**éditeur Word** (SuperDoc) dans un nouvel onglet.

* **Enregistrer** (ou Ctrl + S) réécrit le fichier dans Documents ;
  l'ancienne version reste dans « Gérer les versions ».
* **Télécharger** : télécharge le document tel qu'il est à l'écran.
* Utilisateurs sans droit de modification : lecture seule.
* Ctrl / Maj + clic ou case à cocher : sélection normale (pas d'éditeur).
* Les autres fichiers (PDF, Excel, .doc…) gardent le comportement normal.
* Rien n'est envoyé à l'extérieur ; LibreOffice n'est pas nécessaire.

Dépendance : `documents` (Odoo 18 Enterprise).

## Mise à jour depuis la version 4.x

Remplacer le dossier, redémarrer Odoo, puis Applications → « Aperçu Word » →
**Mettre à niveau**, puis **Ctrl + Maj + R** dans le navigateur.
Les menus « Aperçu Word » / « Documents Word », les actions du menu ⚙ Action
et l'ancien éditeur sont supprimés automatiquement.

## Diagnostic

Console du navigateur (F12) :
* `[Aperçu Word] clic Word actif – version 18.0.5.0.0` → code chargé ;
* `[Aperçu Word] ouverture de <nom>` → clic pris en compte.

## Licence

AGPL-3. Inclut SuperDoc 1.45.0 (AGPL-3.0) — static/lib/superdoc/.
