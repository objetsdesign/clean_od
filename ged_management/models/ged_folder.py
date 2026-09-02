# -*- coding: utf-8 -*-
from odoo import api, fields, models


class GedFolder(models.Model):
    _name = 'ged.folder'
    _description = "Dossier GED"
    _order = 'sequence, name'
    _parent_name = 'parent_id'
    _parent_store = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    folder_type = fields.Selection([
        ('root', 'Racine'),
        ('employee', "Dossier Employé"),
        ('project', "Dossier Projet"),
        ('custom', "Dossier personnalisé"),
    ], string="Type de dossier", default='custom', required=True)

    parent_id = fields.Many2one('ged.folder', string="Dossier parent", ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('ged.folder', 'parent_id', string="Sous-dossiers")

    employee_id = fields.Many2one('hr.employee', string="Employé", ondelete='cascade')
    project_id = fields.Many2one('project.project', string="Projet", ondelete='cascade')

    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company)
    color = fields.Integer(string="Couleur")

    document_ids = fields.One2many('ged.document', 'folder_id', string="Documents")
    document_count = fields.Integer(string="Nb documents", compute='_compute_document_count')

    def _compute_document_count(self):
        grouped = self.env['ged.document']._read_group(
            [('folder_id', 'in', self.ids)], ['folder_id'], ['__count']
        )
        counts = {folder.id: count for folder, count in grouped}
        for rec in self:
            rec.document_count = counts.get(rec.id, 0)

    _sql_constraints = [
        ('employee_folder_uniq', 'unique(employee_id)', "Cet employé possède déjà un dossier GED."),
        ('project_folder_uniq', 'unique(project_id)', "Ce projet possède déjà un dossier GED."),
    ]

    def action_open_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('ged_management.action_ged_document')
        action['domain'] = [('folder_id', '=', self.id)]
        action['context'] = {'default_folder_id': self.id}
        return action
