# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        if not self.env.context.get("shopify_sync"):
            moves.with_context(shopify_sync=True)._shopify_push_stock_after_move()
        return moves

    def _shopify_push_stock_after_move(self):
        """Filet de sécurité : en plus des déclencheurs sur stock.quant,
        pousse explicitement le niveau de stock Shopify pour chaque couple
        (produit, entrepôt) impliqué dans les mouvements validés (réception,
        livraison, transfert interne, ajustement d'inventaire, etc.)."""
        Product = self.env["product.product"].sudo()
        seen = set()
        for move in self:
            product = move.product_id
            if not product.shopify_config_id or not product.shopify_inventory_item_id:
                continue
            for location in (move.location_id, move.location_dest_id):
                warehouse = location.warehouse_id
                if not warehouse:
                    continue
                key = (product.id, warehouse.id)
                if key in seen:
                    continue
                seen.add(key)
                Product._shopify_push_inventory_for_warehouse(product, warehouse)
