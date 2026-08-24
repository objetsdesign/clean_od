# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogBrand(models.Model):
    _name = 'catalog.brand'
    _description = "Marque (ex. Clérieu, Von Ros, Unit Lab)"
    _order = 'sequence, name'

    name = fields.Char(string="Marque", required=True)
    sequence = fields.Integer(string="Séquence", default=10)
    axe_id = fields.Many2one('catalog.axe', string="Axe", required=True, ondelete='cascade', index=True)
    project_id = fields.Many2one(related='axe_id.project_id', string="Projet", store=True, readonly=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    collection_ids = fields.One2many('catalog.collection', 'brand_id', string="Collections")
    collection_count = fields.Integer(string="Nb. collections", compute='_compute_stats', store=True)
    product_count = fields.Integer(string="Nb. références produit", compute='_compute_stats', store=True)

    @api.depends('collection_ids.model_ids.product_ids')
    def _compute_stats(self):
        for rec in self:
            products = rec.collection_ids.mapped('model_ids').mapped('product_ids')
            rec.collection_count = len(rec.collection_ids)
            rec.product_count = len(products)

    def action_view_collections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.collection',
            'view_mode': 'kanban,list,form',
            'domain': [('brand_id', '=', self.id)],
            'context': {'default_brand_id': self.id},
        }
