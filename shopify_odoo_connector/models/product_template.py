# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_product_id = fields.Char(string="ID produit Shopify", copy=False, index=True)
    shopify_handle = fields.Char(string="Handle Shopify")
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")
    shopify_sync_pending = fields.Boolean(default=False, copy=False)

    _sql_constraints = [
        (
            "shopify_product_uniq",
            "unique(shopify_product_id, shopify_config_id)",
            "Ce produit Shopify est déjà importé.",
        ),
    ]

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config):
        """Importe tous les produits de la boutique Shopify `config`."""
        client = config.get_client()
        products = client.rest_get_with_pagination(
            "/products.json", params={"limit": 250}
        )
        for shopify_product in products:
            try:
                self._shopify_create_or_update_from_data(shopify_product, config)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Erreur import produit Shopify %s", shopify_product.get("id"))
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "product.template",
                        "shopify_object_type": "product",
                        "shopify_object_id": str(shopify_product.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        config.last_sync_products = fields.Datetime.now()

    def _shopify_create_or_update_from_data(self, data, config):
        Template = self.env["product.template"].sudo()
        template = Template.search(
            [
                ("shopify_product_id", "=", str(data["id"])),
                ("shopify_config_id", "=", config.id),
            ],
            limit=1,
        )
        vals = {
            "name": data.get("title"),
            "shopify_product_id": str(data["id"]),
            "shopify_handle": data.get("handle"),
            "shopify_config_id": config.id,
            "shopify_last_sync": fields.Datetime.now(),
            "sale_ok": True,
            "purchase_ok": True,
            "type": "consu",
            "is_storable": True,
        }
        ctx_self = self.with_context(shopify_sync=True)
        if template:
            template.with_context(shopify_sync=True).write(vals)
        else:
            template = ctx_self.create(vals)

        self._shopify_sync_variants(template, data.get("variants", []), config)
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "product.template",
                "res_id": template.id,
                "shopify_object_type": "product",
                "shopify_object_id": str(data["id"]),
                "state": "success",
            }
        )
        return template

    def _shopify_sync_variants(self, template, variants_data, config):
        Variant = self.env["product.product"].sudo()
        for variant_data in variants_data:
            variant = Variant.search(
                [
                    ("shopify_variant_id", "=", str(variant_data["id"])),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
            vals = {
                "shopify_variant_id": str(variant_data["id"]),
                "shopify_inventory_item_id": str(variant_data.get("inventory_item_id") or ""),
                "shopify_config_id": config.id,
                "default_code": variant_data.get("sku") or False,
                "barcode": variant_data.get("barcode") or False,
                "list_price": float(variant_data.get("price") or 0.0),
            }
            if variant:
                variant.with_context(shopify_sync=True).write(vals)
            else:
                # Si le template n'a qu'une seule variante par défaut, on la réutilise
                default_variant = template.product_variant_ids[:1]
                if default_variant and not default_variant.shopify_variant_id:
                    default_variant.with_context(shopify_sync=True).write(vals)
                else:
                    vals["product_tmpl_id"] = template.id
                    Variant.with_context(shopify_sync=True).create(vals)

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify
    # ------------------------------------------------------------------
    def action_shopify_push(self):
        for template in self:
            if not template.shopify_config_id:
                continue
            template._shopify_push_one()

    def _shopify_push_one(self):
        self.ensure_one()
        config = self.shopify_config_id
        client = config.get_client()
        payload = {
            "product": {
                "title": self.name,
                "variants": [
                    {
                        "id": int(v.shopify_variant_id) if v.shopify_variant_id else None,
                        "price": str(v.list_price),
                        "sku": v.default_code or "",
                        "barcode": v.barcode or "",
                    }
                    for v in self.product_variant_ids
                ],
            }
        }
        try:
            if self.shopify_product_id:
                result = client.rest_put(
                    f"/products/{self.shopify_product_id}.json", payload
                )
            else:
                result = client.rest_post("/products.json", payload)
                new_id = result.get("product", {}).get("id")
                if new_id:
                    self.with_context(shopify_sync=True).write(
                        {"shopify_product_id": str(new_id), "shopify_config_id": config.id}
                    )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": self.shopify_product_id,
                    "state": "success",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": self.shopify_product_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # Déclenchement automatique (temps réel) Odoo -> Shopify
    # ------------------------------------------------------------------
    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        trigger_fields = {"name", "list_price", "description_sale"}
        if trigger_fields.intersection(vals.keys()):
            for template in self:
                if template.shopify_config_id and template.shopify_config_id.sync_products:
                    template.with_context(shopify_sync=True)._shopify_push_one()
        return result
