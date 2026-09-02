# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectProject(models.Model):
    """ Ajoute un espace documentaire (document.workspace) par projet, créé
    automatiquement, accessible uniquement aux abonnés (membres) du projet. """
    _inherit = 'project.project'

    document_workspace_id = fields.Many2one(
        'document.workspace', string="Espace documents", readonly=True, copy=False
    )
    document_count = fields.Integer(
        string="Nb documents", compute='_compute_document_count'
    )

    def _compute_document_count(self):
        for project in self:
            project.document_count = project.document_workspace_id.document_count

    def _create_document_workspace(self):
        """ Crée le dossier du projet s'il n'existe pas encore.
        privacy_visibility='followers' + project_id renseigné : la règle
        d'accès vérifie directement les abonnés du PROJET (message_partner_ids),
        donc l'accès reste à jour automatiquement si des membres sont
        ajoutés/retirés du projet, sans synchronisation à maintenir. """
        Workspace = self.env['document.workspace'].sudo()
        for project in self:
            if project.document_workspace_id:
                continue
            workspace = Workspace.create({
                'name': "Documents - %s" % project.name,
                'privacy_visibility': 'followers',
                'project_id': project.id,
                'company_id': project.company_id.id or self.env.company.id,
            })
            project.document_workspace_id = workspace.id

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        projects._create_document_workspace()
        return projects

    def action_view_documents(self):
        """ Ouvre le dossier documentaire du projet (bouton intelligent).
        Les documents créés depuis cette vue sont automatiquement rattachés
        au dossier du projet (default_workspace_id dans le contexte). """
        self.ensure_one()
        if not self.document_workspace_id:
            self._create_document_workspace()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'enhanced_document_management.document_file_action'
        )
        action['domain'] = [('workspace_id', '=', self.document_workspace_id.id)]
        action['context'] = {'default_workspace_id': self.document_workspace_id.id}
        return action
