# -*- coding: utf-8 -*-
"""Réactive les produits archivés par erreur dans Odoo pendant leur
changement de boutique (ex : « Produit vonross » retiré de CLERIEU : la
notification Shopify « archivé » archivait aussi le produit dans Odoo), puis
programme leur envoi vers la boutique de leur marque."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    Config = env["shopify.config"]
    templates = env["product.template"].search(
        [
            ("active", "=", False),
            ("shopify_vendor", "!=", False),
            ("default_code", "!=", "SHOPIFY-CUSTOM"),
            ("shopify_target_config_ids", "!=", False),
        ]
    )
    reactivated = 0
    for template in templates:
        shops = Config._shopify_shops_for_brand(template.shopify_vendor)
        # Uniquement si la boutique cochée est bien celle de sa marque et que
        # le produit n'est en ligne sur aucune boutique de sa marque.
        if not shops or template.shopify_target_config_ids != shops:
            continue
        if any(template._shopify_get_link(c).shopify_product_id for c in shops):
            continue
        template.with_context(shopify_sync=True).write(
            {
                "active": True,
                "sale_ok": True,
                "shopify_push_pending": True,
                "shopify_push_config_ids": [(6, 0, shops.ids)],
            }
        )
        reactivated += 1
    _logger.info("Shopify : %s produit(s) réactivé(s) et renvoyé(s) vers leur boutique", reactivated)
