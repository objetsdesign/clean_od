# -*- coding: utf-8 -*-
"""v9.42 : correctif « stock remis à 0 ».

1. Répare les liens de variantes mélangés par l'ancienne association par
   ordre (réassociation par SKU / options, relue dans Shopify).
2. Le « dernier stock commun » est désormais lié à l'article de stock
   Shopify : les anciennes valeurs (sans article) sont ignorées
   automatiquement, on les vide pour la clarté.
3. Réaligne le stock (un stock Shopify n'est plus effacé par un stock Odoo
   vide).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env["shopify.config"].search([("active", "=", True)])
    Template = env["product.template"].sudo()
    for config in configs:
        templates = Template.search([("shopify_link_ids.config_id", "=", config.id)])
        try:
            with cr.savepoint():
                fixed = templates._shopify_repair_variant_links(config)
                _logger.info("Shopify v9.42 : %s lien(s) de variante corrigé(s) pour %s", fixed, config.name)
        except Exception:  # noqa: BLE001
            _logger.exception("Shopify v9.42 : réparation des variantes impossible pour %s", config.name)
    env["shopify.variant.link"].sudo().search(
        [("shopify_stock_agreed", "!=", False)]
    ).with_context(shopify_sync=True).write({"shopify_stock_agreed": False})
    Product = env["product.product"].sudo()
    for config in configs.filtered("sync_inventory"):
        try:
            with cr.savepoint():
                if config.inventory_master == "shopify":
                    Product.shopify_import_inventory_levels(config)
                else:
                    Product.shopify_push_inventory_all(config)
        except Exception:  # noqa: BLE001
            _logger.exception("Shopify v9.42 : alignement du stock impossible pour %s", config.name)
