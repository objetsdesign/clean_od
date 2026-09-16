from datetime import date, datetime

from odoo import api, fields, models


def _as_date(value):
    """date_deadline is a Date field in Community but a Datetime field
    once project_enterprise is installed - normalize to a plain date
    before comparing, whichever edition this runs on."""
    if isinstance(value, datetime):
        return value.date()
    return value


# (name, board_color index into the Board's GROUP_PALETTE - see
# project_board.js) used to seed every project with a sensible default
# set of Board groups.
DEFAULT_BOARD_STAGES = [
    ("A faire", 0),
    ("En cours", 1),
    ("En attente", 2),
    ("Bloqué", 10),
    ("Annulé", 9),
    ("Terminé", 6),
]


class ProjectProject(models.Model):
    _inherit = "project.project"

    board_priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")],
        string="Priority (Board)",
        default="medium",
        help="Priority used by the Monday-style Portfolio view.",
    )
    board_status = fields.Selection(
        [
            ("upcoming", "Upcoming"),
            ("in_progress", "In progress"),
            ("completed", "Completed"),
            ("on_hold", "On hold"),
        ],
        string="Status (Board)",
        default="upcoming",
        help="Workflow status used by the Monday-style Portfolio view.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        for project in projects:
            project._ensure_default_board_stages()
        return projects

    def _ensure_default_board_stages(self):
        """Create the default Board groups (A faire/En cours/.../Terminé)
        for this project if it doesn't already have any stage of its
        own, so a brand new project is never an empty Board with no
        way to add a task."""
        self.ensure_one()
        Stage = self.env["project.task.type"]
        if Stage.search_count([("project_ids", "in", self.id)]):
            return
        for sequence, (name, color) in enumerate(DEFAULT_BOARD_STAGES, start=1):
            Stage.create({
                "name": name,
                "sequence": sequence,
                "project_ids": [(6, 0, [self.id])],
                "board_color": color,
            })

    @api.model
    def od_project_ux_seed_default_stages(self):
        """Backfill: give every existing stage-less project the same
        default Board groups. Runs on every module install/upgrade
        (called from a <function> data record), so it also fixes
        projects that were created before this module added the
        create() override above.
        """
        for project in self.search([("active", "=", True)]):
            project._ensure_default_board_stages()

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

    # ------------------------------------------------------------------
    # Portfolio (Monday-style "board of projects")
    # ------------------------------------------------------------------
    @api.model
    def get_portfolio_data(self):
        Task = self.env["project.task"]
        projects = self.search([("active", "=", True)], order="sequence, name")

        health_selection = dict(self._fields["last_update_status"].selection)
        priority_selection = self._fields["board_priority"].selection
        status_selection = self._fields["board_status"].selection

        today = date.today()
        rows = []
        for project in projects:
            tasks = Task.search([
                ("project_id", "=", project.id),
                ("display_in_project", "=", True),
            ])
            total = len(tasks)
            done = len(tasks.filtered(lambda t: t.state == "1_done"))
            review = len(tasks.filtered(
                lambda t: t.state in ("02_changes_requested", "03_approved")
            ))
            at_risk = len(tasks.filtered(
                lambda t: t.state == "1_canceled"
                or (t.date_deadline and _as_date(t.date_deadline) < today and t.state not in ("1_done", "1_canceled"))
            ))
            in_progress = max(total - done - review - at_risk, 0)

            segments = []
            if total:
                raw = [
                    ("done", done, "#00c875"),
                    ("progress", in_progress, "#fdab3d"),
                    ("review", review, "#a25ddc"),
                    ("risk", at_risk, "#e2445c"),
                ]
                segments = [
                    {"key": key, "pct": round(count / total * 100, 1), "color": color}
                    for key, count, color in raw if count
                ]

            rows.append({
                "id": project.id,
                "name": project.display_name,
                "owner": (
                    {"id": project.user_id.id, "name": project.user_id.name}
                    if project.user_id else False
                ),
                "health": project.last_update_status or "to_define",
                "health_label": health_selection.get(project.last_update_status, "To define"),
                "progress_segments": segments,
                "task_count": total,
                "priority": project.board_priority,
                "priority_label": dict(priority_selection).get(project.board_priority, ""),
                "status": project.board_status,
                "status_label": dict(status_selection).get(project.board_status, ""),
                "date_start": project.date_start and project.date_start.isoformat() or False,
                "date_end": project.date and project.date.isoformat() or False,
            })

        users = self.env["res.users"].search_read(
            [("share", "=", False)], ["id", "name"], order="name", limit=200
        )

        return {
            "projects": rows,
            "priority_options": priority_selection,
            "status_options": status_selection,
            "users": users,
        }

    @api.model
    def create_portfolio_project(self, name):
        project = self.create({"name": name or "New project"})
        return {"id": project.id}
