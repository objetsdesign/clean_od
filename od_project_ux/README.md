# Ob-Jets Design — Project UX — Odoo 18

Pilote UX du module Projets Odoo 18.

## Ce qui est inclus
- **Menus** : trois menus sous l'app Projet — **Projets** (liste de tous
  les projets), **Tâches** (board d'un projet par étapes) et
  **Mes tâches** (même design que Tâches, groupé par projet, toutes vos
  tâches assignées). Les trois sont fournis par ce module, donc garantis
  présents quelle que soit l'édition/version d'Odoo. Les menus natifs
  Odoo "Projects", "Tasks" et "My Tasks" sont automatiquement masqués
  pour éviter les doublons, et le menu "Overview" (dashboard KPI) a été
  retiré — le dashboard reste disponible en interne mais n'a plus
  d'entrée de menu.
- **Projets** (`Projects > Projets`) : liste de tous les projets façon Monday — pastille Owner, **Project health** (couleur
  reprenant le statut natif Odoo), **barre de progression segmentée**
  (calculée à partir de la répartition réelle des statuts de tâches),
  **Priorité** et **Statut** éditables en un clic, **Planned timeline**
  (dates natives `date_start` / `date`), recherche, filtre par santé
  (chips cliquables Off track / At risk / On track), regroupement
  (Owner / Santé / Priorité / Statut), masquage de colonnes, ajout rapide
  de projet.
- **Tâches façon Monday.com** (`Projects > Tâches`) : groupes colorés (stages),
  tâches en lignes, colonnes Statut / Priorité / Tags / Personnes / Début /
  Échéance **éditables directement dans le tableau** (pas besoin d'ouvrir la
  fiche), drag & drop d'une tâche vers un autre groupe, ajout rapide de
  tâche par groupe, couleur de groupe personnalisable, sélecteur de projet
  en haut.
- **Timeline / Gantt** intégrée à Tâches (onglet "Timeline") : mêmes
  groupes colorés, barres positionnées entre "Début" et "Échéance",
  navigation par semaines, clic sur une barre ou un nom = ouvre la tâche.
- Bouton "Tâches" sur la fiche projet et sur chaque carte Kanban projet.
- Kanban Projet plus lisible, sans remplacer le Kanban natif.
- Résumé visuel dans la fiche Projet.
- Dashboard simple avec 5 KPI.
- Liste des projets actifs avec progression et statut.
- Responsive desktop/tablette/mobile.
- Aucun fichier du core Odoo modifié — Tâches lit/écrit uniquement
  `project.task` (`state`, `priority`, `tag_ids`, `user_ids`,
  `date_deadline`, `stage_id`), ajoute un champ `od_date_start` (Date de
  début, utilisé par la Timeline) sur `project.task`, un champ
  `board_color` sur `project.task.type` pour la couleur des groupes, et
  deux champs `board_priority` / `board_status` sur `project.project`
  pour le Portfolio (la Timeline du Portfolio réutilise les champs natifs
  `date_start` / `date`).

## Installation
1. Copier le dossier `od_project_ux` dans un répertoire addons.
2. Redémarrer Odoo.
3. Mettre à jour la liste des applications.
4. Installer `Ob-Jets Design - Project UX`.
5. Aller dans `Projects > Projets` ou `Projects > Tâches`.

## Principe
Le module hérite des vues natives Odoo et utilise les modèles `project.project` et `project.task`.
Le dashboard calcule les KPI à la demande et ne crée pas de données métier dupliquées.

## Validation recommandée
Faire valider d'abord :
- couleurs ;
- densité ;
- KPI ;
- vocabulaire ;
- organisation des cartes.

Puis généraliser le principe aux autres modules.
