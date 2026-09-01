# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ---------- Lien vers le catalogue ----------
    catalog_product_ids = fields.One2many(
        'catalog.product', 'product_tmpl_id', string="Références catalogue liées",
    )
    catalog_product_count = fields.Integer(
        string="Nb. références catalogue", compute='_compute_catalog_product_count',
    )
    in_catalog = fields.Boolean(
        string="Dans le catalogue", compute='_compute_catalog_product_count', store=True,
        help="Vrai si ce produit Odoo est rattaché à au moins une référence du catalogue "
             "(collection / modèle / variante).",
    )

    # ---------- Statut de stock (réel, basé sur l'inventaire Odoo) ----------
    catalog_stock_alert_threshold = fields.Integer(
        string="Seuil d'alerte stock", default=5,
        help="En dessous (ou égal à) de ce seuil de quantité disponible, le produit est "
             "considéré en stock faible. À zéro ou moins : rupture de stock.",
    )
    catalog_stock_status = fields.Selection(
        [
            ('rupture', "Rupture de stock"),
            ('faible', "Stock faible"),
            ('disponible', "Disponible"),
        ],
        string="Statut du stock (Odoo)",
        compute='_compute_catalog_stock_status', store=True,
        help="État du stock disponible réel (inventaire Odoo), calculé à partir de la "
             "quantité disponible (qty_available) et du seuil d'alerte.",
    )

    @api.depends('catalog_product_ids')
    def _compute_catalog_product_count(self):
        for rec in self:
            rec.catalog_product_count = len(rec.catalog_product_ids)
            rec.in_catalog = bool(rec.catalog_product_ids)

    @api.depends('qty_available', 'catalog_stock_alert_threshold', 'type')
    def _compute_catalog_stock_status(self):
        for rec in self:
            qty = rec.qty_available or 0.0
            if qty <= 0:
                rec.catalog_stock_status = 'rupture'
            elif qty <= rec.catalog_stock_alert_threshold:
                rec.catalog_stock_status = 'faible'
            else:
                rec.catalog_stock_status = 'disponible'

    def action_view_catalog_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Références catalogue liées",
            'res_model': 'catalog.product',
            'view_mode': 'list,kanban,form',
            'domain': [('product_tmpl_id', '=', self.id)],
        }
