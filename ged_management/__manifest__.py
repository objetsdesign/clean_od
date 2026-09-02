# -*- coding: utf-8 -*-
{
    'name': "GED - Documents Employés & Projets",
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Gestion Électronique des Documents (dossiers, catégories) liée aux Employés et Projets",
    'description': """
GED - Gestion Électronique des Documents
=========================================
Module de gestion documentaire interne (indépendant de l'app Documents native) :
- Un DOSSIER (ged.folder) par employé, créé automatiquement
- Un DOSSIER par projet, créé automatiquement
- Navigation par dossiers en Kanban, catégories, statuts (Brouillon/Validé/Archivé)
- Chaque employé voit : ses propres créations, le contenu de SON dossier employé,
  et les documents des projets dont il est membre
- Les Administrateurs / Responsables RH voient tout, sans restriction
""",
    'author': "Custom",
    'license': 'LGPL-3',
    'depends': ['hr', 'project', 'mail'],
    'data': [
        'security/ged_security.xml',
        'security/ir.model.access.csv',
        'data/ged_folder_data.xml',
        'data/ged_sequence.xml',
        'views/ged_folder_views.xml',
        'views/ged_document_views.xml',
        'views/ged_category_views.xml',
        'views/hr_employee_views.xml',
        'views/project_project_views.xml',
        'views/ged_menu.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
}
