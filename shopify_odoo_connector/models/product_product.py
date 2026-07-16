# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_variant_id = fields.Char(string="ID variante Shopify", copy=False, index=True)
    shopify_inventory_item_id = fields.Char(string="ID inventory item Shopify", copy=False)
    shopify_variant_image_id = fields.Char(string="ID photo de variante Shopify", copy=False)

    _sql_constraints = [
        (
            "shopify_variant_uniq",
            "unique(shopify_variant_id, shopify_config_id)",
            "Cette variante Shopify est déjà importée.",
        ),
    ]

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        if "list_price" in vals or "default_code" in vals:
            for variant in self:
                if variant.shopify_config_id and variant.shopify_variant_id:
                    variant.product_tmpl_id.with_context(
                        shopify_sync=True
                    )._shopify_push_one()
        return result
