from odoo import api, fields, models


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"

    board_color = fields.Integer(
        string="Board Color",
        default=-1,
        help="Color of this stage's group header in the Monday-style "
             "Board view. -1 means the color is picked automatically.",
    )

    @api.model
    def create_board_stage(self, project_id, name):
        """Create a new stage (Board group) for a project, from the
        Board's '+ Nouveau groupe' control. Needed because a brand new
        project has no stages at all, so there is otherwise nowhere to
        add a task from this view.
        """
        last = self.search(
            [("project_ids", "in", project_id)], order="sequence desc", limit=1
        )
        stage = self.create({
            "name": name or "Nouveau groupe",
            "project_ids": [(4, project_id)],
            "sequence": (last.sequence + 1) if last else 1,
        })
        return {
            "id": stage.id,
            "name": stage.name,
            "board_color": stage.board_color,
            "tasks": [],
        }
