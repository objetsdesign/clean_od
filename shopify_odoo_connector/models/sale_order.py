# -*- coding: utf-8 -*-
import logging

from datetime import datetime, timezone

from odoo import fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)

FINANCIAL_STATUS_MAP = {
    "paid": "paid",
    "partially_paid": "partial",
    "refunded": "refunded",
    "partially_refunded": "partial_refund",
    "pending": "pending",
    "voided": "voided",
}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_order_id = fields.Char(string="ID commande Shopify", copy=False, index=True)
    shopify_order_number = fields.Char(string="N° commande Shopify")
    shopify_financial_status = fields.Char(string="Statut financier Shopify")
    shopify_fulfillment_status = fields.Char(string="Statut expédition Shopify")
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")

    _sql_constraints = [
        (
            "shopify_order_uniq",
            "unique(shopify_order_id, shopify_config_id)",
            "Cette commande Shopify est déjà importée.",
        ),
    ]

    @staticmethod
    def _shopify_parse_datetime(value):
        """Convertit une date ISO 8601 Shopify (ex: '2026-07-12T03:33:03+02:00')
        en datetime naïf UTC compatible avec les champs Datetime d'Odoo."""
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            _logger.warning("Date Shopify illisible, ignorée : %s", value)
            return False
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config):
        client = config.get_client()
        orders = client.rest_get_with_pagination(
            "/orders.json", params={"limit": 250, "status": "any"}
        )
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    self._shopify_create_or_update_from_data(order, config)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Erreur import commande Shopify %s", order.get("id"))
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "sale.order",
                        "shopify_object_type": "order",
                        "shopify_object_id": str(order.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        config.last_sync_orders = fields.Datetime.now()

    def _shopify_create_or_update_from_data(self, data, config):
        Order = self.env["sale.order"].sudo()
        order = Order.search(
            [
                ("shopify_order_id", "=", str(data["id"])),
                ("shopify_config_id", "=", config.id),
            ],
            limit=1,
        )

        partner = self._shopify_get_or_create_partner(data, config)

        vals = {
            "partner_id": partner.id,
            "shopify_config_id": config.id,
            "shopify_order_id": str(data["id"]),
            "shopify_order_number": str(data.get("order_number") or data.get("name")),
            "shopify_financial_status": data.get("financial_status"),
            "shopify_fulfillment_status": data.get("fulfillment_status") or "unfulfilled",
            "shopify_last_sync": fields.Datetime.now(),
        }
        if config.order_team_id:
            vals["team_id"] = config.order_team_id.id
        if config.default_pricelist_id:
            vals["pricelist_id"] = config.default_pricelist_id.id

        if order:
            order.with_context(shopify_sync=True).write(vals)
        else:
            vals["date_order"] = self._shopify_parse_datetime(data.get("created_at"))
            order = Order.with_context(shopify_sync=True).create(vals)

        self._shopify_sync_order_lines(order, data.get("line_items", []), config)

        # Confirmer automatiquement la commande (si elle est encore en devis)
        # permet à Odoo de générer automatiquement le bon de livraison
        # correspondant, comme il le ferait pour n'importe quelle vente.
        if (
            config.auto_confirm_orders
            and order.state in ("draft", "sent")
            and not data.get("cancelled_at")
        ):
            try:
                order.with_context(shopify_sync=True).action_confirm()
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "Impossible de confirmer automatiquement la commande Shopify %s : %s",
                    order.shopify_order_number, exc,
                )

        if data.get("financial_status") == "paid":
            order._shopify_register_payment(data, config)

        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "sale.order",
                "res_id": order.id,
                "shopify_object_type": "order",
                "shopify_object_id": str(data["id"]),
                "state": "success",
            }
        )
        return order

    def _shopify_get_or_create_partner(self, data, config):
        Partner = self.env["res.partner"].sudo()
        customer_data = data.get("customer")
        if customer_data:
            partner = Partner.search(
                [
                    ("shopify_customer_id", "=", str(customer_data["id"])),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
            if not partner:
                partner = Partner._shopify_create_or_update_from_data(customer_data, config)
            return partner
        # Commande "invité" sans compte client
        email = (data.get("email") or data.get("contact_email") or "guest@shopify").strip()
        partner = Partner.search([("email", "=", email)], limit=1)
        if not partner:
            partner = Partner.create({"name": email, "email": email})
        return partner

    def _shopify_sync_order_lines(self, order, line_items, config):
        Line = self.env["sale.order.line"].sudo()
        Product = self.env["product.product"].sudo()
        for item in line_items:
            variant = Product.search(
                [
                    ("shopify_variant_id", "=", str(item.get("variant_id"))),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
            existing_line = Line.search(
                [
                    ("order_id", "=", order.id),
                    ("shopify_line_item_id", "=", str(item["id"])),
                ],
                limit=1,
            )
            vals = {
                "order_id": order.id,
                "shopify_line_item_id": str(item["id"]),
                "product_uom_qty": item.get("quantity", 1),
                "price_unit": float(item.get("price") or 0.0),
                "name": item.get("title") or (variant.display_name if variant else "Article Shopify"),
            }
            if variant:
                vals["product_id"] = variant.id
            if existing_line:
                existing_line.with_context(shopify_sync=True).write(vals)
            else:
                Line.with_context(shopify_sync=True).create(vals)

    # ------------------------------------------------------------------
    # Paiements
    # ------------------------------------------------------------------
    def _shopify_register_payment(self, data, config):
        self.ensure_one()
        Payment = self.env["account.payment"].sudo()
        for transaction in data.get("transactions", []) or []:
            if transaction.get("status") != "success" or transaction.get("kind") not in (
                "sale",
                "capture",
            ):
                continue
            existing = Payment.search(
                [("shopify_transaction_id", "=", str(transaction["id"]))], limit=1
            )
            if existing:
                continue
            Payment.create(
                {
                    "partner_id": self.partner_id.id,
                    "amount": float(transaction.get("amount") or 0.0),
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "shopify_transaction_id": str(transaction["id"]),
                    "shopify_config_id": config.id,
                    "shopify_order_id": self.shopify_order_id,
                    "ref": f"Shopify {self.shopify_order_number}",
                }
            )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify (statut annulation)
    # ------------------------------------------------------------------
    def action_shopify_cancel(self):
        for order in self:
            if not order.shopify_order_id:
                continue
            client = order.shopify_config_id.get_client()
            try:
                client.rest_post(f"/orders/{order.shopify_order_id}/cancel.json", {})
            except ShopifyAPIError as exc:
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": order.shopify_config_id.id,
                        "direction": "out",
                        "model_name": "sale.order",
                        "res_id": order.id,
                        "shopify_object_type": "order",
                        "shopify_object_id": order.shopify_order_id,
                        "state": "error",
                        "message": str(exc),
                    }
                )

    def action_cancel(self):
        result = super().action_cancel()
        if not self.env.context.get("shopify_sync"):
            for order in self:
                if order.shopify_order_id:
                    order.with_context(shopify_sync=True).action_shopify_cancel()
        return result
