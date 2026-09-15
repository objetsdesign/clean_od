from odoo import fields, models


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"

    board_color = fields.Integer(
        string="Board Color",
        default=-1,
        help="Color of this stage's group header in the Monday-style "
             "Board view. -1 means the color is picked automatically.",
    )
