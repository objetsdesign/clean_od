# -*- coding: utf-8 -*-
{
    'name': "GED - Documents Employés & Projets",
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Gestion Électronique des Documents (GED) des employés, liée aux Projets",
    'description': """
GED - Gestion Électronique des Documents
=========================================
Ce module permet de :
- Centraliser et stocker les documents de chaque employé (contrats, CV, diplômes, pièces d'identité, etc.)
- Lier les documents à un Projet (module Project) en plus (ou à la place) d'un employé
- Classer les documents par catégorie
- Restreindre l'accès : chaque employé ne voit que les documents de son propre dossier
- Donner un accès complet à l'Administrateur GED (tous les documents, tous les employés, tous les projets)
- Voir les documents directement depuis la fiche Employé et la fiche Projet (bouton intelligent)
""",
    'author': "Custom",
    'license': 'LGPL-3',
    'depends': ['hr', 'project', 'mail'],
    'data': [
        'security/ged_security.xml',
        'security/ir.model.access.csv',
        'data/ged_sequence.xml',
        'views/ged_document_views.xml',
        'views/ged_category_views.xml',
        'views/hr_employee_views.xml',
        'views/project_project_views.xml',
        'views/ged_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
