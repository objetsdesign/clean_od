# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductImage(models.Model):
    _inherit = "product.image"

    shopify_image_id = fields.Char(string="ID image Shopify", copy=False, index=True)
    shopify_image_hash = fields.Char(
        string="Empreinte image Shopify",
        copy=False,
        help="Empreinte (MD5) de la dernière version de cette image envoyée vers Shopify.",
    )

    def unlink(self):
        # Si l'image supprimée avait déjà été poussée vers Shopify, on la
        # supprime aussi côté Shopify pour rester synchronisé (sauf si la
        # suppression vient elle-même d'une synchro entrante Shopify).
        if not self.env.context.get("shopify_sync"):
            for image in self:
                if not image.shopify_image_id or not image.product_tmpl_id:
                    continue
                for link in image.product_tmpl_id.shopify_link_ids:
                    image.product_tmpl_id._shopify_delete_image(link.config_id, image.shopify_image_id)
        return super().unlink()
