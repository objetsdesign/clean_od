# -*- coding: utf-8 -*-
from odoo import api, fields, models


class GedDocument(models.Model):
    _name = 'ged.document'
    _description = "Document GED"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    reference = fields.Char(string="Référence", readonly=True, copy=False, default='Nouveau')
    name = fields.Char(string="Titre du document", required=True, tracking=True)

    folder_id = fields.Many2one(
        'ged.folder', string="Dossier", required=True, tracking=True,
        domain="[('folder_type', '!=', 'root')]",
        ondelete='restrict',
    )
    # Champs "raccourcis", dérivés du dossier, stockés pour permettre
    # des règles d'accès simples et des recherches/regroupements rapides.
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", related='folder_id.employee_id',
        store=True, readonly=True, index=True,
    )
    project_id = fields.Many2one(
        'project.project', string="Projet", related='folder_id.project_id',
        store=True, readonly=True, index=True,
    )

    category_id = fields.Many2one('ged.document.category', string="Catégorie", tracking=True)

    file = fields.Binary(string="Fichier", required=True, attachment=True)
    filename = fields.Char(string="Nom du fichier")

    date_document = fields.Date(string="Date du document", default=fields.Date.context_today)
    description = fields.Text(string="Notes / Description")

    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company, required=True)
    user_id = fields.Many2one('res.users', string="Ajouté par", default=lambda self: self.env.user, readonly=True)

    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('validated', 'Validé'),
        ('archived', 'Archivé'),
    ], string="État", default='draft', tracking=True)

    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'Nouveau') == 'Nouveau':
                vals['reference'] = self.env['ir.sequence'].next_by_code('ged.document') or 'Nouveau'
        return super().create(vals_list)

    def action_validate(self):
        self.write({'state': 'validated'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_archive_document(self):
        self.write({'state': 'archived', 'active': False})

    def action_unarchive_document(self):
        self.write({'state': 'draft', 'active': True})
