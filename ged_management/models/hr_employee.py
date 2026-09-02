# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ged_folder_id = fields.Many2one(
        'ged.folder', string="Dossier GED", readonly=True, copy=False
    )
    ged_document_count = fields.Integer(
        string="Nb documents", compute='_compute_ged_document_count'
    )

    def _compute_ged_document_count(self):
        for employee in self:
            employee.ged_document_count = employee.ged_folder_id.document_count

    def _ged_create_folder(self):
        """ Crée le dossier GED personnel de l'employé s'il n'existe pas encore. """
        Folder = self.env['ged.folder'].sudo()
        root = self.env.ref('ged_management.ged_folder_root_employees', raise_if_not_found=False)
        for employee in self:
            if employee.ged_folder_id:
                continue
            folder = Folder.create({
                'name': employee.name,
                'folder_type': 'employee',
                'employee_id': employee.id,
                'parent_id': root.id if root else False,
                'company_id': employee.company_id.id or self.env.company.id,
            })
            employee.ged_folder_id = folder.id

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._ged_create_folder()
        return employees

    def action_view_ged_documents(self):
        """ Ouvre directement le dossier GED de l'employé. """
        self.ensure_one()
        if not self.ged_folder_id:
            self._ged_create_folder()
        action = self.env['ir.actions.act_window']._for_xml_id('ged_management.action_ged_folder')
        action['res_id'] = self.ged_folder_id.id
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        return action
