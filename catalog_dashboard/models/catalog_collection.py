# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogCollection(models.Model):
    _name = 'catalog.collection'
    _description = "Collection du catalogue produit"
    _order = 'sequence, name'

    name = fields.Char(string="Collection", required=True)
    sequence = fields.Integer(string="Séquence", default=10)
    accent_color = fields.Char(
        string="Couleur d'accent",
        default='#9C6B3E',
        help="Couleur héxadécimale utilisée pour l'étiquette de la collection dans les fiches produit.",
    )
    color = fields.Integer(string="Couleur Kanban", default=1)
    description = fields.Char(string="Description / fournisseur")
    active = fields.Boolean(default=True)

    product_ids = fields.One2many(
        'catalog.product', 'collection_id', string="Références produit"
    )

    product_count = fields.Integer(string="Nb. références", compute='_compute_stats', store=True)
    total_stock = fields.Integer(string="Stock total", compute='_compute_stats', store=True)
    avg_cost = fields.Float(string="Coût moyen", compute='_compute_stats', store=True, digits=(12, 3))
    realise_count = fields.Integer(string="Réalisé", compute='_compute_stats', store=True)
    en_cours_count = fields.Integer(string="En cours", compute='_compute_stats', store=True)
    a_planifier_count = fields.Integer(string="À planifier", compute='_compute_stats', store=True)

    @api.depends('product_ids.stock', 'product_ids.cout_production', 'product_ids.status')
    def _compute_stats(self):
        for rec in self:
            products = rec.product_ids
            rec.product_count = len(products)
            rec.total_stock = sum(products.mapped('stock'))
            costs = [c for c in products.mapped('cout_production') if c]
            rec.avg_cost = (sum(costs) / len(costs)) if costs else 0.0
            rec.realise_count = len(products.filtered(lambda p: p.status == 'realise'))
            rec.en_cours_count = len(products.filtered(lambda p: p.status == 'en_cours'))
            rec.a_planifier_count = len(products.filtered(lambda p: p.status == 'a_planifier'))

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.product',
            'view_mode': 'kanban,list,form',
            'domain': [('collection_id', '=', self.id)],
            'context': {'default_collection_id': self.id},
        }
