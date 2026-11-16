# -*- coding: utf-8 -*-
"""v9.38 : Odoo = référence du stock. Réalignement complet (même logique que v9.36).
reliés au même entrepôt recevaient chacun tout le stock Odoo. On réaligne
tout de suite le stock Shopify : emplacement principal = stock Odoo,
emplacements en doublon = 0."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env["product.product"].sudo()
    for config in env["shopify.config"].search([("active", "=", True), ("sync_inventory", "=", True)]):
        try:
            Product.shopify_push_inventory_all(config)
        except Exception:  # noqa: BLE001
            _logger.exception("Shopify v9.38 : réalignement du stock impossible pour %s", config.name)
