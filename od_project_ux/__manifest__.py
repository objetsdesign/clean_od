{
    "name": "Ob-Jets Design - Project UX",
    "version": "18.0.1.0.0",
    "category": "Project",
    "summary": "Monday.com-style Board, dashboard and UX improvements for Odoo 18 Projects",
    "description": "Project UX for Odoo 18: adds a Monday.com-style Board view "
                    "(colored groups, inline-editable status/priority/tags/"
                    "assignees/due dates, drag & drop between groups) on top "
                    "of native project.task/project.project data, plus a KPI "
                    "dashboard and a clearer Kanban/form. No core Odoo file "
                    "is modified.",
    "author": "Ob-Jets Design",
    "license": "LGPL-3",
    "depends": ["project"],
    "data": [
        "views/project_views.xml",
        "views/project_dashboard.xml",
        "views/project_board.xml",
        "views/project_my_tasks.xml",
        "views/project_portfolio.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "od_project_ux/static/src/scss/project_ux.scss",
            "od_project_ux/static/src/js/project_dashboard.js",
            "od_project_ux/static/src/js/project_board.js",
            "od_project_ux/static/src/js/project_portfolio.js",
            "od_project_ux/static/src/xml/project_dashboard.xml",
            "od_project_ux/static/src/xml/project_board.xml",
            "od_project_ux/static/src/xml/project_portfolio.xml"
        ]
    },
    "installable": True,
    "application": False
}
