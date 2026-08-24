# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogModel(models.Model):
    _name = 'catalog.model'
    _description = "Modèle produit (regroupe les variantes / références SKU)"
    _order = 'collection_id, sequence, name'

    name = fields.Char(string="Modèle", required=True)
    sequence = fields.Integer(string="Séquence", default=10)
    collection_id = fields.Many2one('catalog.collection', string="Collection", required=True,
                                     ondelete='cascade', index=True, tracking=False)
    brand_id = fields.Many2one(related='collection_id.brand_id', string="Marque", store=True, readonly=True)
    axe_id = fields.Many2one(related='collection_id.axe_id', string="Axe", store=True, readonly=True)
    accent_color = fields.Char(related='collection_id.accent_color', string="Couleur collection", store=False)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    product_ids = fields.One2many('catalog.product', 'model_id', string="Variantes / SKU")
    variant_count = fields.Integer(string="Nb. variantes", compute='_compute_stats', store=True)
    total_stock = fields.Integer(string="Stock total", compute='_compute_stats', store=True)
    late_count = fields.Integer(string="En retard", compute='_compute_stats', store=True)

    cover_image_1920 = fields.Image(
        string="Photo de couverture", compute='_compute_cover_image', store=False,
        help="Reprend automatiquement la photo de la première variante du modèle.",
    )

    @api.depends('product_ids.image_1920')
    def _compute_cover_image(self):
        for rec in self:
            cover = False
            for product in rec.product_ids.sorted('id'):
                if product.image_1920:
                    cover = product.image_1920
                    break
            rec.cover_image_1920 = cover

    @api.depends('product_ids.stock', 'product_ids.is_late')
    def _compute_stats(self):
        for rec in self:
            rec.variant_count = len(rec.product_ids)
            rec.total_stock = sum(rec.product_ids.mapped('stock'))
            rec.late_count = len(rec.product_ids.filtered('is_late'))

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.product',
            'view_mode': 'kanban,list,form',
            'domain': [('model_id', '=', self.id)],
            'context': {'default_model_id': self.id},
        }
