# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogAxe(models.Model):
    _name = 'catalog.axe'
    _description = "Axe produit (famille : Luminaire, Bougie, Parfum d'ambiance, Textile, Bagagerie, B2B...)"
    _order = 'sequence, name'

    name = fields.Char(string="Axe", required=True)
    sequence = fields.Integer(string="Séquence", default=10)
    project_id = fields.Many2one('catalog.project', string="Projet", required=True, ondelete='cascade', index=True)
    description = fields.Text(string="Description")
    accent_color = fields.Char(string="Couleur d'accent", default='#8C5A34')
    active = fields.Boolean(default=True)

    brand_ids = fields.One2many('catalog.brand', 'axe_id', string="Marques")
    brand_count = fields.Integer(string="Nb. marques", compute='_compute_stats', store=True)
    collection_count = fields.Integer(string="Nb. collections", compute='_compute_stats', store=True)
    product_count = fields.Integer(string="Nb. références produit", compute='_compute_stats', store=True)
    late_count = fields.Integer(string="Produits en retard", compute='_compute_stats', store=True)
    low_stock_count = fields.Integer(string="Stock faible / rupture", compute='_compute_stats', store=True)

    @api.depends(
        'brand_ids.collection_count', 'brand_ids.product_count',
        'brand_ids.collection_ids.model_ids.product_ids.is_late',
        'brand_ids.collection_ids.model_ids.product_ids.stock_status',
    )
    def _compute_stats(self):
        for rec in self:
            products = rec.brand_ids.mapped('collection_ids').mapped('model_ids').mapped('product_ids')
            rec.brand_count = len(rec.brand_ids)
            rec.collection_count = sum(rec.brand_ids.mapped('collection_count'))
            rec.product_count = len(products)
            rec.late_count = len(products.filtered('is_late'))
            rec.low_stock_count = len(products.filtered(lambda p: p.stock_status in ('faible', 'rupture')))

    def action_view_brands(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.brand',
            'view_mode': 'kanban,list,form',
            'domain': [('axe_id', '=', self.id)],
            'context': {'default_axe_id': self.id},
        }
