from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    # Tags utilisés par les tâches du projet (et non les tags du projet lui-même)
    task_tag_ids = fields.Many2many(
        "project.tags",
        string="Tags des tâches",
        compute="_compute_task_tag_ids",
    )

    def _compute_task_tag_ids(self):
        for project in self:
            project.task_tag_ids = project.task_ids.tag_ids

    def action_open_timesheets(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hr_timesheet.timesheet_action_all")
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {
            "default_project_id": self.id,
            "search_default_project_id": self.id,
        }
        action["display_name"] = "Feuilles de temps - %s" % self.name
        return action
