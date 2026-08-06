# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Une variante peut être liée à PLUSIEURS boutiques Shopify (une ligne
    # shopify.variant.link par boutique) : voir shopify_multi_store.py.
    shopify_variant_link_ids = fields.One2many(
        "shopify.variant.link", "product_id", string="Variantes Shopify liées"
    )

    def _shopify_get_variant_link(self, config):
        self.ensure_one()
        if not config:
            return self.env["shopify.variant.link"]
        return self.shopify_variant_link_ids.filtered(lambda l: l.config_id == config)[:1]

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        if "list_price" in vals or "default_code" in vals or "image_variant_1920" in vals:
            for variant in self:
                for config in variant.shopify_variant_link_ids.config_id:
                    variant.product_tmpl_id.with_context(
                        shopify_sync=True
                    )._shopify_push_one(config=config)
        return result
