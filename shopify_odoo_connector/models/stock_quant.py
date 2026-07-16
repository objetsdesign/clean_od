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
        if "quantity" in vals or "inventory_quantity" in vals:
            for quant in self:
                quant._shopify_push_inventory_level()
        return result

    def _shopify_push_inventory_level(self):
        self.ensure_one()
        product = self.product_id
        if not product.shopify_config_id or not product.shopify_inventory_item_id:
            return
        warehouse = self.location_id.warehouse_id
        if not warehouse:
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
        client = product.shopify_config_id.get_client()
        available = int(self.quantity - self.reserved_quantity)
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
