{
    'name': 'Project Kanban Custom',
    'version': '18.0.1.0.0',
    'category': 'Services/Project',
    'summary': 'Carte kanban projet allégée : titre réduit, sans dates, tags des tâches, lien feuilles de temps',
    'depends': ['project', 'hr_timesheet'],
    'data': ['views/project_project_views.xml'],
    'assets': {
        'web.assets_backend': ['project_kanban_custom/static/src/scss/kanban.scss'],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
