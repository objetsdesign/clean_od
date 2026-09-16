from datetime import datetime

from odoo import api, fields, models


def _date_str(value):
    """date_deadline is a Date field in Community but a Datetime field
    once project_enterprise is installed - always return a plain
    'YYYY-MM-DD' string (what <input type="date"> expects), whichever
    edition this runs on."""
    if not value:
        return False
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


class ProjectTask(models.Model):
    _inherit = "project.task"

    od_date_start = fields.Date(
        string="Start Date (Board)",
        help="Start date used by the Monday-style Board/Timeline view. "
             "Purely a planning helper, independent from native scheduling.",
    )

    def _board_task_vals(self, group_key):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "priority": self.priority,
            "date_deadline": _date_str(self.date_deadline),
            "od_date_start": self.od_date_start and self.od_date_start.isoformat() or False,
            "tag_ids": [
                {"id": tag.id, "name": tag.name, "color": tag.color}
                for tag in self.tag_ids
            ],
            "user_ids": [
                {"id": user.id, "name": user.name}
                for user in self.user_ids
            ],
            "stage_id": group_key,
        }

    # ------------------------------------------------------------------
    # Board (Monday-style) view
    # ------------------------------------------------------------------
    @api.model
    def get_board_data(self, project_id=False):
        """Return everything the Board OWL component needs to render:
        the list of switchable projects, the groups (stages) with their
        tasks, and the option lists used by the inline editors.
        """
        Project = self.env["project.project"]
        projects = Project.search_read(
            [("active", "=", True)], ["id", "name"], order="name"
        )

        project = Project.browse(project_id) if project_id else Project
        if not project or not project.exists():
            project = Project.search([("active", "=", True)], limit=1)

        if not project:
            return {
                "project": False,
                "projects": projects,
                "groups": [],
                "tags": [],
                "users": [],
                "state_options": [],
                "priority_options": [],
                "my_tasks_mode": False,
            }

        Stage = self.env["project.task.type"]
        stages = Stage.search(
            [("project_ids", "in", project.id)], order="sequence, id"
        )

        domain = [("project_id", "=", project.id), ("display_in_project", "=", True)]
        tasks = self.search(domain, order="stage_id, priority desc, sequence, id")

        fg = self.fields_get(["state", "priority"], attributes=["selection"])
        state_options = fg["state"]["selection"]
        priority_options = fg["priority"]["selection"]

        groups_map = {}
        groups_order = []
        for stage in stages:
            groups_map[stage.id] = {
                "id": stage.id,
                "name": stage.name,
                "board_color": stage.board_color,
                "tasks": [],
            }
            groups_order.append(stage.id)

        no_stage_key = False
        for task in tasks:
            stage = task.stage_id
            key = stage.id if stage else no_stage_key
            if key not in groups_map:
                groups_map[key] = {
                    "id": key,
                    "name": stage.name if stage else "No stage",
                    "board_color": -1,
                    "tasks": [],
                }
                groups_order.append(key)
            groups_map[key]["tasks"].append(task._board_task_vals(key))

        tags = self.env["project.tags"].search_read([], ["id", "name", "color"])
        users = self.env["res.users"].search_read(
            [("share", "=", False)], ["id", "name"], order="name", limit=200
        )

        return {
            "project": {"id": project.id, "name": project.name},
            "projects": projects,
            "groups": [groups_map[key] for key in groups_order],
            "tags": tags,
            "users": users,
            "state_options": state_options,
            "priority_options": priority_options,
            "my_tasks_mode": False,
        }

    @api.model
    def get_my_board_data(self):
        """Same shape as get_board_data, but cross-project: tasks
        assigned to the current user, grouped by project instead of by
        stage. Powers the 'Mes tâches' menu with the same Board design.
        """
        tasks = self.search([
            ("user_ids", "in", [self.env.uid]),
            ("display_in_project", "=", True),
        ], order="project_id, priority desc, sequence, id")

        fg = self.fields_get(["state", "priority"], attributes=["selection"])
        state_options = fg["state"]["selection"]
        priority_options = fg["priority"]["selection"]

        groups_map = {}
        groups_order = []
        no_project_key = False
        for task in tasks:
            project = task.project_id
            key = project.id if project else no_project_key
            if key not in groups_map:
                groups_map[key] = {
                    "id": key,
                    "name": project.name if project else "Sans projet",
                    "board_color": -1,
                    "tasks": [],
                }
                groups_order.append(key)
            groups_map[key]["tasks"].append(task._board_task_vals(key))

        tags = self.env["project.tags"].search_read([], ["id", "name", "color"])
        users = self.env["res.users"].search_read(
            [("share", "=", False)], ["id", "name"], order="name", limit=200
        )

        return {
            "project": {"id": 0, "name": "Mes tâches"},
            "projects": [],
            "groups": [groups_map[key] for key in groups_order],
            "tags": tags,
            "users": users,
            "state_options": state_options,
            "priority_options": priority_options,
            "my_tasks_mode": True,
        }

    @api.model
    def create_board_task(self, project_id, stage_id, name):
        """Create a task from the Board's inline 'Add task' row."""
        vals = {
            "name": name or "New task",
            "project_id": project_id,
        }
        if stage_id:
            vals["stage_id"] = stage_id
        task = self.create(vals)
        return task._board_task_vals(task.stage_id.id if task.stage_id else False)

    @api.model
    def create_my_task(self, project_id, name):
        """Create a task from the 'Mes tâches' inline 'Add task' row: same
        as create_board_task, but also assigns it to the current user
        since that view is filtered to 'my' tasks.
        """
        task = self.create({
            "name": name or "New task",
            "project_id": project_id,
            "user_ids": [(4, self.env.uid)],
        })
        return task._board_task_vals(task.project_id.id if task.project_id else False)

    @api.model
    def set_board_stage_color(self, stage_id, color):
        self.env["project.task.type"].browse(stage_id).write({"board_color": color})
        return True

    @api.model
    def set_task_date(self, task_id, field, value):
        """Write a date-ish field (currently only date_deadline) that may
        be either Date (Community) or Datetime (once project_enterprise
        is installed), from a plain 'YYYY-MM-DD' string coming from an
        <input type="date">. Writing a bare date string straight to a
        Datetime field can fail, so this appends a time part when needed.
        """
        if field not in ("date_deadline", "od_date_start"):
            return False
        task = self.browse(task_id)
        if not value:
            task.write({field: False})
            return True
        if self._fields[field].type == "datetime":
            value = f"{value} 00:00:00"
        task.write({field: value})
        return True
