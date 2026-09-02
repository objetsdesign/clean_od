# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectTask(models.Model):
    """ Une tâche n'a pas son propre dossier : elle utilise le dossier
    documentaire de SON PROJET (project_id.document_workspace_id), pour que
    tous les documents d'un même projet (qu'ils soient attachés au projet
    ou à l'une de ses tâches) se retrouvent au même endroit. """
    _inherit = 'project.task'

    document_workspace_id = fields.Many2one(
        'document.workspace', string="Espace documents",
        related='project_id.document_workspace_id', store=False, readonly=True,
    )
    document_count = fields.Integer(
        string="Nb documents", compute='_compute_document_count'
    )

    def _compute_document_count(self):
        for task in self:
            task.document_count = task.document_workspace_id.document_count

    def action_view_documents(self):
        """ Ouvre le dossier documentaire du projet de la tâche (bouton
        intelligent). Tout document ajouté depuis cette fenêtre est
        automatiquement rattaché au dossier du projet. """
        self.ensure_one()
        if not self.project_id:
            return {'type': 'ir.actions.act_window_close'}
        if not self.project_id.document_workspace_id:
            self.project_id._create_document_workspace()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'enhanced_document_management.document_file_action'
        )
        action['domain'] = [('workspace_id', '=', self.project_id.document_workspace_id.id)]
        action['context'] = {'default_workspace_id': self.project_id.document_workspace_id.id}
        return action
