# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyDeletedOrder(models.Model):
    """Commandes Shopify supprimées volontairement dans Odoo : elles ne
    doivent plus être réimportées (webhook ou synchronisation planifiée)."""

    _name = "shopify.deleted.order"
    _description = "Commande Shopify supprimée dans Odoo"
    _order = "create_date desc"

    config_id = fields.Many2one("shopify.config", string="Boutique", required=True, ondelete="cascade", index=True)
    shopify_order_id = fields.Char(string="ID commande Shopify", required=True, index=True)
    name = fields.Char(string="Commande")

    _sql_constraints = [
        ("shopify_deleted_order_uniq", "unique(config_id, shopify_order_id)",
         "Cette commande est déjà marquée comme supprimée."),
    ]

    @api.model
    def _shopify_mark_deleted(self, config, shopify_order_id, name=None):
        if not config or not shopify_order_id:
            return
        if not self._shopify_is_deleted(config, shopify_order_id):
            self.create({"config_id": config.id, "shopify_order_id": str(shopify_order_id), "name": name})

    @api.model
    def _shopify_is_deleted(self, config, shopify_order_id):
        if not config or not shopify_order_id:
            return False
        return bool(self.search_count([
            ("config_id", "=", config.id),
            ("shopify_order_id", "=", str(shopify_order_id)),
        ], limit=1))
