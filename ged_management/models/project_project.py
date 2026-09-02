# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ged_folder_id = fields.Many2one(
        'ged.folder', string="Dossier GED", readonly=True, copy=False
    )
    ged_document_count = fields.Integer(
        string="Nb documents", compute='_compute_ged_document_count'
    )

    def _compute_ged_document_count(self):
        for project in self:
            project.ged_document_count = project.ged_folder_id.document_count

    def _ged_create_folder(self):
        """ Crée le dossier GED du projet s'il n'existe pas encore. """
        Folder = self.env['ged.folder'].sudo()
        root = self.env.ref('ged_management.ged_folder_root_projects', raise_if_not_found=False)
        for project in self:
            if project.ged_folder_id:
                continue
            folder = Folder.create({
                'name': project.name,
                'folder_type': 'project',
                'project_id': project.id,
                'parent_id': root.id if root else False,
                'company_id': project.company_id.id or self.env.company.id,
            })
            project.ged_folder_id = folder.id

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        projects._ged_create_folder()
        return projects

    def action_view_ged_documents(self):
        """ Ouvre directement le dossier GED du projet. """
        self.ensure_one()
        if not self.ged_folder_id:
            self._ged_create_folder()
        action = self.env['ir.actions.act_window']._for_xml_id('ged_management.action_ged_folder')
        action['res_id'] = self.ged_folder_id.id
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        return action
