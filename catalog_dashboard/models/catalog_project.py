# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogProject(models.Model):
    _name = 'catalog.project'
    _description = "Projet (niveau racine du catalogue)"
    _order = 'sequence, name'

    name = fields.Char(string="Projet", required=True, default="Objets Design")
    sequence = fields.Integer(string="Séquence", default=10)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    axe_ids = fields.One2many('catalog.axe', 'project_id', string="Axes")
    axe_count = fields.Integer(string="Nb. axes", compute='_compute_stats', store=True)
    product_count = fields.Integer(string="Nb. références produit", compute='_compute_stats', store=True)

    @api.depends('axe_ids.product_count')
    def _compute_stats(self):
        for rec in self:
            rec.axe_count = len(rec.axe_ids)
            rec.product_count = sum(rec.axe_ids.mapped('product_count'))

    def action_view_axes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.axe',
            'view_mode': 'kanban,list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
