# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployee(models.Model):
    """ Ajoute un espace documentaire (document.workspace) personnel et
    privé à chaque employé, créé automatiquement. """
    _inherit = 'hr.employee'

    document_workspace_id = fields.Many2one(
        'document.workspace', string="Espace documents", readonly=True, copy=False
    )
    document_count = fields.Integer(
        string="Nb documents", compute='_compute_document_count'
    )

    def _compute_document_count(self):
        for employee in self:
            employee.document_count = employee.document_workspace_id.document_count

    def _create_document_workspace(self):
        """ Crée le dossier personnel de l'employé s'il n'existe pas encore.
        privacy_visibility='followers' + aucun follower ajouté : seul le
        lien employee_id (utilisé par la règle d'accès) donne l'accès,
        donc pas besoin de synchroniser des followers qui pourraient
        devenir obsolètes. """
        Workspace = self.env['document.workspace'].sudo()
        for employee in self:
            if employee.document_workspace_id:
                continue
            workspace = Workspace.create({
                'name': "Documents - %s" % employee.name,
                'privacy_visibility': 'followers',
                'employee_id': employee.id,
                'company_id': employee.company_id.id or self.env.company.id,
            })
            employee.document_workspace_id = workspace.id

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._create_document_workspace()
        return employees

    def action_view_documents(self):
        """ Ouvre le dossier documentaire de l'employé (bouton intelligent). """
        self.ensure_one()
        if not self.document_workspace_id:
            self._create_document_workspace()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'enhanced_document_management.document_file_action'
        )
        action['domain'] = [('workspace_id', '=', self.document_workspace_id.id)]
        action['context'] = {'default_workspace_id': self.document_workspace_id.id}
        return action
