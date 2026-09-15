from datetime import date

from odoo import api, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    @api.model
    def get_ux_dashboard_data(self):
        """Return lightweight, read-only KPIs using native Odoo data."""
        Project = self.env["project.project"]
        Task = self.env["project.task"]

        active_projects = Project.search([("active", "=", True)])

        open_task_domain = [
            ("state", "not in", ["1_done", "1_canceled"]),
            ("project_id", "!=", False),
        ]
        overdue_task_domain = open_task_domain + [
            ("date_deadline", "<", date.today()),
        ]

        open_tasks = Task.search_count(open_task_domain)
        overdue_tasks = Task.search_count(overdue_task_domain)
        completed_projects = Project.search_count([
            ("active", "=", True),
            ("last_update_status", "=", "done"),
        ])

        percentages = [
            p.task_completion_percentage
            for p in active_projects
            if p.task_count
        ]
        average_progress = (
            round(sum(percentages) / len(percentages), 1)
            if percentages else 0.0
        )

        selection = dict(Project._fields["last_update_status"].selection)
        top_projects = []
        for project in active_projects.sorted(
            key=lambda p: (p.task_completion_percentage, p.name.lower()),
            reverse=True,
        )[:8]:
            top_projects.append({
                "id": project.id,
                "name": project.display_name,
                "customer": project.partner_id.display_name or "",
                "manager": project.user_id.name or "",
                "progress": round(project.task_completion_percentage or 0.0, 1),
                "open_tasks": project.open_task_count,
                "status": project.last_update_status or "to_define",
                "status_label": selection.get(
                    project.last_update_status, "To define"
                ),
            })

        return {
            "active_projects": len(active_projects),
            "open_tasks": open_tasks,
            "overdue_tasks": overdue_tasks,
            "completed_projects": completed_projects,
            "average_progress": average_progress,
            "projects": top_projects,
        }
