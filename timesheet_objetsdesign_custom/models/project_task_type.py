from odoo import api, fields, models

class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    project_ids = fields.Many2many(
        'project.project',
        'project_task_type_rel',
        'type_id',
        'project_id',
        string='Projects',
        help="Projects in which this stage is present."
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if not self._context.get('active_id'):  # active_id existe si on modifie
            project_ids = self.env['project.project'].search([('user_id', '=', self.env.uid)]).ids
            if project_ids:
                res['project_ids'] = [(6, 0, project_ids)]
        return res
