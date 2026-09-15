from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    od_date_start = fields.Date(
        string="Start Date (Board)",
        help="Start date used by the Monday-style Board/Timeline view. "
             "Purely a planning helper, independent from native scheduling.",
    )

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
            groups_map[key]["tasks"].append({
                "id": task.id,
                "name": task.name,
                "state": task.state,
                "priority": task.priority,
                "date_deadline": task.date_deadline and task.date_deadline.isoformat() or False,
                "od_date_start": task.od_date_start and task.od_date_start.isoformat() or False,
                "tag_ids": [
                    {"id": tag.id, "name": tag.name, "color": tag.color}
                    for tag in task.tag_ids
                ],
                "user_ids": [
                    {"id": user.id, "name": user.name}
                    for user in task.user_ids
                ],
                "stage_id": key,
            })

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
        return {
            "id": task.id,
            "name": task.name,
            "state": task.state,
            "priority": task.priority,
            "date_deadline": False,
            "od_date_start": False,
            "tag_ids": [],
            "user_ids": [],
            "stage_id": task.stage_id.id if task.stage_id else False,
        }

    @api.model
    def set_board_stage_color(self, stage_id, color):
        self.env["project.task.type"].browse(stage_id).write({"board_color": color})
        return True
