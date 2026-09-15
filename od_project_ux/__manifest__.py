{
    "name": "Ob-Jets Design - Project UX",
    "version": "18.0.1.0.0",
    "category": "Project",
    "summary": "Progressive UX improvements for Odoo 18 Projects",
    "description": "Project UX pilot for Odoo 18. Keeps native Project workflow while improving readability, visual hierarchy, Kanban, form and dashboard.",
    "author": "Ob-Jets Design",
    "license": "LGPL-3",
    "depends": ["project"],
    "data": [
        "views/project_views.xml",
        "views/project_dashboard.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "od_project_ux/static/src/scss/project_ux.scss",
            "od_project_ux/static/src/js/project_dashboard.js",
            "od_project_ux/static/src/xml/project_dashboard.xml"
        ]
    },
    "installable": True,
    "application": False
}
