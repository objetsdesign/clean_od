# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    shopify_fulfillment_id = fields.Char(string="ID fulfillment Shopify", copy=False)

    def button_validate(self):
        result = super().button_validate()
        for picking in self:
            sale_order = picking.sale_id
            if (
                sale_order
                and sale_order.shopify_order_id
                and sale_order.shopify_config_id
                and sale_order.shopify_config_id.sync_fulfillments
                and picking.state == "done"
                and not picking.shopify_fulfillment_id
            ):
                picking._shopify_create_fulfillment(sale_order)
        return result

    def _shopify_create_fulfillment(self, sale_order):
        self.ensure_one()
        config = sale_order.shopify_config_id
        client = config.get_client()

        line_items_by_shopify_id = []
        for move in self.move_ids:
            sale_line = move.sale_line_id
            if sale_line and sale_line.shopify_line_item_id:
                line_items_by_shopify_id.append(
                    {
                        "id": int(sale_line.shopify_line_item_id),
                        "quantity": int(move.quantity),
                    }
                )

        payload = {
            "fulfillment": {
                "line_items_by_fulfillment_order": [],
                "tracking_info": {
                    "number": self.carrier_tracking_ref or "",
                    "company": self.carrier_id.name if self.carrier_id else "",
                },
                "notify_customer": True,
            }
        }
        try:
            # Récupération des fulfillment orders liés à la commande (API moderne)
            fo_data = client.rest_get(
                f"/orders/{sale_order.shopify_order_id}/fulfillment_orders.json"
            )
            fulfillment_orders = fo_data.get("fulfillment_orders", [])
            if not fulfillment_orders:
                return
            payload["fulfillment"]["line_items_by_fulfillment_order"] = [
                {"fulfillment_order_id": fo["id"]} for fo in fulfillment_orders
            ]
            result = client.rest_post("/fulfillments.json", payload)
            fulfillment_id = result.get("fulfillment", {}).get("id")
            if fulfillment_id:
                self.shopify_fulfillment_id = str(fulfillment_id)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "stock.picking",
                    "res_id": self.id,
                    "shopify_object_type": "fulfillment",
                    "shopify_object_id": self.shopify_fulfillment_id,
                    "state": "success",
                }
            )
        except ShopifyAPIError as exc:
            _logger.error("Erreur création fulfillment Shopify : %s", exc)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "stock.picking",
                    "res_id": self.id,
                    "shopify_object_type": "fulfillment",
                    "state": "error",
                    "message": str(exc),
                }
            )
