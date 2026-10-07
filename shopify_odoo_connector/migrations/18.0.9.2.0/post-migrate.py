# -*- coding: utf-8 -*-
"""La marque choisit la boutique : chaque produit dont la marque est celle
d'une boutique (CLERIEU, VONROS/VONROSS, UNITLAB) est affiché sur CETTE
boutique uniquement. Les produits sans marque de boutique ne sont pas
modifiés (rien n'est retiré par erreur)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    Config = env["shopify.config"]
    Config._shopify_migrate_shop_brands()
    templates = env["product.template"].search(
        [("shopify_vendor", "!=", False), ("default_code", "!=", "SHOPIFY-CUSTOM")]
    )
    count = 0
    for template in templates:
        shops = Config._shopify_shops_for_brand(template.shopify_vendor)
        if not shops or shops == template.shopify_target_config_ids:
            continue
        old_links = template.shopify_link_ids.config_id
        template.with_context(shopify_sync=True).write(
            {
                "shopify_target_config_ids": [(6, 0, shops.ids)],
                # Envoi sur la nouvelle boutique + archivage sur l'ancienne.
                "shopify_push_pending": True,
                "shopify_push_config_ids": [(6, 0, (shops | old_links).ids)],
            }
        )
        count += 1
    _logger.info("Shopify : boutique d'affichage alignée sur la marque pour %s produits", count)
