# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CatalogCollection(models.Model):
    _name = 'catalog.collection'
    _description = "Collection du catalogue produit"
    _order = 'sequence, name'

    name = fields.Char(string="Collection", required=True)
    sequence = fields.Integer(string="Séquence", default=10)

    brand_id = fields.Many2one('catalog.brand', string="Marque", required=True, ondelete='restrict', index=True)
    axe_id = fields.Many2one(related='brand_id.axe_id', string="Axe", store=True, readonly=True)
    project_id = fields.Many2one(related='brand_id.axe_id.project_id', string="Projet", store=True, readonly=True)

    accent_color = fields.Char(
        string="Couleur d'accent",
        default='#9C6B3E',
        help="Couleur héxadécimale utilisée pour l'étiquette de la collection dans les fiches produit.",
    )
    color = fields.Integer(string="Couleur Kanban", default=1)
    description = fields.Char(string="Description / fournisseur")
    active = fields.Boolean(default=True)

    model_ids = fields.One2many('catalog.model', 'collection_id', string="Modèles")
    product_ids = fields.One2many(
        'catalog.product', compute='_compute_product_ids', string="Références produit (variantes)",
    )

    model_count = fields.Integer(string="Nombre de modèles", compute='_compute_stats', store=True)
    product_count = fields.Integer(
        string="Nombre de références produit", compute='_compute_stats', store=True,
        help="Nombre de références produit (variantes SKU) rattachées à cette collection, tous modèles confondus. "
             "Ce chiffre n'est pas une référence ou un identifiant de la collection elle-même.",
    )
    total_stock = fields.Integer(string="Stock total", compute='_compute_stats', store=True)
    avg_cost = fields.Float(
        string="Coût de production moyen (interne)", compute='_compute_stats', store=True, digits=(12, 3),
        help="Moyenne du coût de production interne des références. Ne représente ni un prix de revient ni un prix de vente.",
    )
    disponible_count = fields.Integer(string="Produit disponible", compute='_compute_stats', store=True)
    en_developpement_count = fields.Integer(string="En développement (idée → pré-série)", compute='_compute_stats', store=True)
    en_production_count = fields.Integer(string="En production", compute='_compute_stats', store=True)
    low_stock_count = fields.Integer(string="Stock faible ou en rupture", compute='_compute_stats', store=True)
    favorite_count = fields.Integer(string="Coups de cœur", compute='_compute_stats', store=True)
    late_count = fields.Integer(string="Produits en retard", compute='_compute_stats', store=True)

    cover_image_1920 = fields.Image(
        string="Photo de couverture", compute='_compute_cover_image', store=False,
        help="Reprend automatiquement la photo de la première référence produit de la collection.",
    )

    @api.depends('model_ids.product_ids')
    def _compute_product_ids(self):
        for rec in self:
            rec.product_ids = rec.model_ids.mapped('product_ids')

    @api.depends('model_ids.product_ids.image_1920')
    def _compute_cover_image(self):
        for rec in self:
            cover = False
            for product in rec.model_ids.mapped('product_ids').sorted('id'):
                if product.image_1920:
                    cover = product.image_1920
                    break
            rec.cover_image_1920 = cover

    @api.depends(
        'model_ids.product_ids.stock', 'model_ids.product_ids.cout_production',
        'model_ids.product_ids.dev_stage', 'model_ids.product_ids.stock_status',
        'model_ids.product_ids.favorite', 'model_ids.product_ids.is_late',
    )
    def _compute_stats(self):
        for rec in self:
            products = rec.model_ids.mapped('product_ids')
            rec.model_count = len(rec.model_ids)
            rec.product_count = len(products)
            rec.total_stock = sum(products.mapped('stock'))
            costs = [c for c in products.mapped('cout_production') if c]
            rec.avg_cost = (sum(costs) / len(costs)) if costs else 0.0
            rec.disponible_count = len(products.filtered(lambda p: p.dev_stage == 'produit_disponible'))
            rec.en_developpement_count = len(products.filtered(
                lambda p: p.dev_stage in ('idee', 'design', 'sourcing', 'prototype_v0',
                                           'prototype_valide', 'bat_valide', 'pre_serie')))
            rec.en_production_count = len(products.filtered(
                lambda p: p.dev_stage in ('production_planifiee', 'production_en_cours')))
            rec.low_stock_count = len(products.filtered(lambda p: p.stock_status in ('faible', 'rupture')))
            rec.favorite_count = len(products.filtered('favorite'))
            rec.late_count = len(products.filtered('is_late'))

    def action_view_models(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.model',
            'view_mode': 'kanban,list,form',
            'domain': [('collection_id', '=', self.id)],
            'context': {'default_collection_id': self.id},
        }

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'catalog.product',
            'view_mode': 'kanban,list,form',
            'domain': [('collection_id', '=', self.id)],
            'context': {},
        }
