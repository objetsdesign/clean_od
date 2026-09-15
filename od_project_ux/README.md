# Ob-Jets Design — Project UX — Odoo 18

Pilote UX du module Projets Odoo 18.

## Ce qui est inclus
- **Board façon Monday.com** (`Projects > Board`) : groupes colorés (stages),
  tâches en lignes, colonnes Statut / Priorité / Tags / Personnes / Échéance
  **éditables directement dans le tableau** (pas besoin d'ouvrir la fiche),
  drag & drop d'une tâche vers un autre groupe, ajout rapide de tâche par
  groupe, couleur de groupe personnalisable, sélecteur de projet en haut.
- Bouton "Board" sur la fiche projet et sur chaque carte Kanban projet.
- Kanban Projet plus lisible, sans remplacer le Kanban natif.
- Résumé visuel dans la fiche Projet.
- Dashboard simple avec 5 KPI.
- Liste des projets actifs avec progression et statut.
- Responsive desktop/tablette/mobile.
- Aucun fichier du core Odoo modifié — le Board lit/écrit uniquement
  `project.task` (`state`, `priority`, `tag_ids`, `user_ids`,
  `date_deadline`, `stage_id`) et ajoute un simple champ `board_color`
  sur `project.task.type` pour la couleur des groupes.

## Installation
1. Copier le dossier `od_project_ux` dans un répertoire addons.
2. Redémarrer Odoo.
3. Mettre à jour la liste des applications.
4. Installer `Ob-Jets Design - Project UX`.
5. Aller dans `Projects > Overview` ou `Projects > Board`.

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
