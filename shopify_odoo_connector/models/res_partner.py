# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_customer_id = fields.Char(string="ID client Shopify", copy=False, index=True)
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")

    _sql_constraints = [
        (
            "shopify_customer_uniq",
            "unique(shopify_customer_id, shopify_config_id)",
            "Ce client Shopify est déjà importé.",
        ),
    ]

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config, updated_at_min=None):
        client = config.get_client()
        params = {"limit": 250}
        if updated_at_min:
            params["updated_at_min"] = fields.Datetime.to_string(updated_at_min)
        customers = client.rest_get_with_pagination("/customers.json", params=params)
        for customer in customers:
            try:
                with self.env.cr.savepoint():
                    self._shopify_create_or_update_from_data(customer, config)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Erreur import client Shopify %s", customer.get("id"))
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "res.partner",
                        "shopify_object_type": "customer",
                        "shopify_object_id": str(customer.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        config.last_sync_customers = fields.Datetime.now()

    def _shopify_create_or_update_from_data(self, data, config):
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search(
            [
                ("shopify_customer_id", "=", str(data["id"])),
                ("shopify_config_id", "=", config.id),
            ],
            limit=1,
        )
        default_address = data.get("default_address") or {}
        vals = {
            "name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            or data.get("email")
            or "Client Shopify",
            "email": data.get("email"),
            "phone": data.get("phone") or default_address.get("phone"),
            "street": default_address.get("address1"),
            "street2": default_address.get("address2"),
            "city": default_address.get("city"),
            "zip": default_address.get("zip"),
            "shopify_customer_id": str(data["id"]),
            "shopify_config_id": config.id,
            "shopify_last_sync": fields.Datetime.now(),
            "customer_rank": 1,
        }
        country = default_address.get("country_code")
        if country:
            country_rec = self.env["res.country"].sudo().search(
                [("code", "=", country)], limit=1
            )
            if country_rec:
                vals["country_id"] = country_rec.id
        if partner:
            partner.with_context(shopify_sync=True).write(vals)
        else:
            matched_partner = False
            if self._shopify_avoid_duplicate_customers_enabled():
                matched_partner = self._shopify_find_existing_partner(data)
            if matched_partner:
                partner = matched_partner
                partner.with_context(shopify_sync=True).write(vals)
            else:
                partner = Partner.with_context(shopify_sync=True).create(vals)
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "res.partner",
                "res_id": partner.id,
                "shopify_object_type": "customer",
                "shopify_object_id": str(data["id"]),
                "state": "success",
            }
        )
        return partner

    # ------------------------------------------------------------------
    # Anti-doublons : réutiliser un contact Odoo existant (même email) au
    # lieu d'en créer un nouveau, s'il n'est pas déjà lié à une autre
    # boutique Shopify.
    # ------------------------------------------------------------------
    def _shopify_avoid_duplicate_customers_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "shopify_odoo_connector.avoid_duplicate_customers", "True"
        ) in ("True", "1", 1, True)

    def _shopify_find_existing_partner(self, data):
        email = (data.get("email") or "").strip()
        if not email:
            return False
        Partner = self.env["res.partner"].sudo()
        return Partner.search(
            [("shopify_config_id", "=", False), ("email", "=ilike", email)], limit=1
        )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify
    # ------------------------------------------------------------------
    def action_shopify_push(self):
        for partner in self:
            if partner.shopify_config_id:
                partner._shopify_push_one()

    def _shopify_push_one(self):
        self.ensure_one()
        config = self.shopify_config_id
        client = config.get_client()
        name_parts = (self.name or "").split(" ", 1)
        payload = {
            "customer": {
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "email": self.email,
                "phone": self.phone,
            }
        }
        try:
            if self.shopify_customer_id:
                client.rest_put(f"/customers/{self.shopify_customer_id}.json", payload)
            else:
                result = client.rest_post("/customers.json", payload)
                new_id = result.get("customer", {}).get("id")
                if new_id:
                    self.with_context(shopify_sync=True).write(
                        {"shopify_customer_id": str(new_id)}
                    )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "res.partner",
                    "res_id": self.id,
                    "shopify_object_type": "customer",
                    "state": "error",
                    "message": str(exc),
                }
            )

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        trigger_fields = {"name", "email", "phone", "street", "city", "zip"}
        if trigger_fields.intersection(vals.keys()):
            for partner in self:
                if partner.shopify_config_id and partner.shopify_config_id.sync_customers:
                    partner.with_context(shopify_sync=True)._shopify_push_one()
        return result
