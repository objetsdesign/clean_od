# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Une variante peut être liée à PLUSIEURS boutiques Shopify (une ligne
    # shopify.variant.link par boutique) : voir shopify_multi_store.py.
    shopify_variant_link_ids = fields.One2many(
        "shopify.variant.link", "product_id", string="Variantes Shopify liées"
    )
    # Champ related "à plat" sur la variante : nécessaire car le "Regrouper
    # par" d'une vue de recherche Odoo ne sait pas suivre un chemin en
    # pointillés (ex: "product_tmpl_id.shopify_config_ids") — il lui faut un
    # champ défini directement sur le modèle de la vue.
    shopify_config_ids = fields.Many2many(
        "shopify.config",
        relation="product_product_shopify_config_rel",
        column1="product_product_id",
        column2="shopify_config_id",
        related="product_tmpl_id.shopify_config_ids",
        string="Boutiques Shopify",
        store=True,
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
            # Comme product_template.write() : une variante jamais encore
            # liée à aucune boutique (produit créé/modifié directement dans
            # Odoo, jamais explicitement envoyé vers Shopify) doit quand
            # même être poussée vers la boutique par défaut. Sans ce repli,
            # déposer une photo de variante (image_variant_1920) sur un
            # produit pas encore lié ne l'envoyait jamais vers Shopify.
            default_config = self.env["shopify.config"]._shopify_default_config()
            for variant in self:
                configs = variant.shopify_variant_link_ids.filtered(
                    lambda l: l.config_id.sync_products
                ).mapped("config_id")
                if not configs and default_config and default_config.sync_products:
                    configs = default_config
                for config in configs:
                    variant.product_tmpl_id.with_context(
                        shopify_sync=True
                    )._shopify_push_one(config=config)
        return result
