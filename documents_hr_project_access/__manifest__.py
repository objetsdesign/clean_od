# -*- coding: utf-8 -*-
{
    'name': "Documents - Accès RH & Projet",
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Corrige les droits d'accès du module Documents standard : dossier employé personnel + créations propres",
    'description': """
Ce module N'AJOUTE AUCUN NOUVEAU MODÈLE, AUCUNE NOUVELLE VUE.
Il utilise à 100% l'app Documents standard d'Odoo (documents.document) et se contente
de corriger les règles d'accès (ir.rule) :

- Un utilisateur standard ne voit, dans les documents liés à un Employé (res_model = 'hr.employee'),
  QUE ceux liés à SA PROPRE fiche employé, plus tout document qu'il a lui-même créé (n'importe où).
- Les documents non liés à un employé (factures, contrats fournisseurs, signatures, etc.) ne sont
  PAS touchés : leur visibilité reste celle configurée nativement (onglet "Accès" du dossier/document).
- Les Administrateurs (Réglages) et Responsables RH voient tout, sans restriction.

IMPORTANT - à propos des documents de Projet :
Le partage des documents d'un Projet avec ses membres est déjà géré nativement par Odoo
(bridge "documents_project") via l'onglet Accès du dossier du projet. Ce comportement polymorphe
(res_model / res_id) ne peut pas être re-filtré de façon fiable par une règle ir.rule statique
sans ajouter un champ technique supplémentaire sur documents.document. Pour restreindre precisément
les documents d'un projet à ses seuls membres, configurez l'onglet "Accès" du dossier du projet
(Projet > Documents > icône dossier > Accès), ou demandez-moi le module complémentaire qui ajoute
un champ project_id calculé pour automatiser cela.
""",
    'author': "Custom",
    'license': 'LGPL-3',
    'depends': ['documents', 'hr'],
    'data': [
        'security/documents_hr_security.xml',
    ],
    'installable': True,
    'application': False,
}
