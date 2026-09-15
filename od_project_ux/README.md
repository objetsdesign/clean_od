# Ob-Jets Design — Project UX — Odoo 18

Pilote UX du module Projets Odoo 18.

## Ce qui est inclus
- Kanban Projet plus lisible, sans remplacer le Kanban natif.
- Résumé visuel dans la fiche Projet.
- Dashboard simple avec 5 KPI.
- Liste des projets actifs avec progression et statut.
- Responsive desktop/tablette/mobile.
- Aucun fichier du core Odoo modifié.

## Installation
1. Copier le dossier `od_project_ux` dans un répertoire addons.
2. Redémarrer Odoo.
3. Mettre à jour la liste des applications.
4. Installer `Ob-Jets Design - Project UX`.
5. Aller dans `Projects > Overview`.

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
