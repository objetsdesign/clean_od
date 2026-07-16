# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        if "quantity" in vals or "inventory_quantity" in vals or "reserved_quantity" in vals:
            self._shopify_push_touched_pairs()
        return result

    def create(self, vals_list):
        quants = super().create(vals_list)
        if not self.env.context.get("shopify_sync"):
            quants._shopify_push_touched_pairs()
        return quants

    def _shopify_push_touched_pairs(self):
        """Regroupe les quants par (produit, entrepôt) et ne pousse qu'un seul
        appel API par combinaison, même si plusieurs quants/lots sont touchés
        en même temps (ex: transfert avec plusieurs numéros de série)."""
        seen = set()
        for quant in self:
            product = quant.product_id
            warehouse = quant.location_id.warehouse_id
            if not product or not warehouse:
                continue
            key = (product.id, warehouse.id)
            if key in seen:
                continue
            seen.add(key)
            self.env["product.product"].sudo()._shopify_push_inventory_for_warehouse(
                product, warehouse
            )


class ProductProductStockSync(models.Model):
    _inherit = "product.product"

    def _shopify_push_inventory_for_warehouse(self, product, warehouse):
        """Calcule la quantité disponible (physique - réservée) du produit
        dans l'entrepôt donné, en agrégeant tous les quants concernés, puis
        pousse le résultat vers Shopify (inventory_levels/set)."""
        product = product.sudo()
        if not product.shopify_config_id or not product.shopify_inventory_item_id:
            return
        if not warehouse or not warehouse.lot_stock_id:
            return

        location = self.env["shopify.location"].sudo().search(
            [
                ("warehouse_id", "=", warehouse.id),
                ("config_id", "=", product.shopify_config_id.id),
            ],
            limit=1,
        )
        if not location:
            return

        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", warehouse.lot_stock_id.id),
            ]
        )
        available = int(sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity")))

        client = product.shopify_config_id.get_client()
        try:
            client.rest_post(
                "/inventory_levels/set.json",
                {
                    "location_id": int(location.shopify_location_id),
                    "inventory_item_id": int(product.shopify_inventory_item_id),
                    "available": max(available, 0),
                },
            )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": product.shopify_config_id.id,
                    "direction": "out",
                    "model_name": "product.product",
                    "res_id": product.id,
                    "shopify_object_type": "inventory_level",
                    "shopify_object_id": product.shopify_inventory_item_id,
                    "state": "success",
                    "message": f"Entrepôt {warehouse.name} : {max(available, 0)} disponible(s)",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": product.shopify_config_id.id,
                    "direction": "out",
                    "model_name": "product.product",
                    "res_id": product.id,
                    "shopify_object_type": "inventory_level",
                    "shopify_object_id": product.shopify_inventory_item_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

