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

    product_count = fields.Integer(
        string="Nombre de références produit", compute='_compute_stats', store=True,
        help="Nombre de références produit (SKU) rattachées à cette collection. "
             "Ce chiffre n'est pas une référence ou un identifiant de la collection elle-même.",
    )
    total_stock = fields.Integer(string="Stock total", compute='_compute_stats', store=True)
    avg_cost = fields.Float(
        string="Coût de production moyen (interne)", compute='_compute_stats', store=True, digits=(12, 3),
        help="Moyenne du coût de production interne des références. Ne représente ni un prix de revient ni un prix de vente.",
    )
    realise_count = fields.Integer(string="Production réalisée", compute='_compute_stats', store=True)
    en_cours_count = fields.Integer(string="Production en cours", compute='_compute_stats', store=True)
    a_planifier_count = fields.Integer(string="Production à planifier", compute='_compute_stats', store=True)
    low_stock_count = fields.Integer(string="Stock faible ou en rupture", compute='_compute_stats', store=True)
    favorite_count = fields.Integer(string="Coups de cœur", compute='_compute_stats', store=True)

    cover_image_1920 = fields.Image(
        string="Photo de couverture", compute='_compute_cover_image', store=False,
        help="Reprend automatiquement la photo de la première référence produit de la collection.",
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

    @api.depends('product_ids.stock', 'product_ids.cout_production', 'product_ids.status',
                 'product_ids.low_stock', 'product_ids.favorite')
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
            rec.low_stock_count = len(products.filtered('low_stock'))
            rec.favorite_count = len(products.filtered('favorite'))

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
