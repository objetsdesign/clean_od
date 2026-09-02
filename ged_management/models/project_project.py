# -*- coding: utf-8 -*-
from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ged_document_ids = fields.One2many(
        'ged.document', 'project_id', string="Documents GED"
    )
    ged_document_count = fields.Integer(
        string="Nb documents", compute='_compute_ged_document_count'
    )

    def _compute_ged_document_count(self):
        grouped = self.env['ged.document']._read_group(
            [('project_id', 'in', self.ids)],
            ['project_id'], ['__count']
        )
        counts = {project.id: count for project, count in grouped}
        for proj in self:
            proj.ged_document_count = counts.get(proj.id, 0)

    def action_view_ged_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ged_management.action_ged_document'
        )
        action['domain'] = [('project_id', '=', self.id)]
        action['context'] = {
            'default_project_id': self.id,
            'search_default_project_id': self.id,
        }
        return action
