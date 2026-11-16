# -*- coding: utf-8 -*-
"""v9.40 : stock synchronisé dans les deux sens. Les boutiques passent en
« Odoo et Shopify », puis un premier alignement fixe le stock commun de
départ (Odoo fait foi pour ce premier passage)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env["shopify.config"].search([("active", "=", True)])
    configs.filtered(lambda c: c.inventory_master == "odoo").write({"inventory_master": "both"})
    Product = env["product.product"].sudo()
    for config in configs.filtered("sync_inventory"):
        try:
            Product.shopify_push_inventory_all(config)
        except Exception:  # noqa: BLE001
            _logger.exception("Shopify v9.40 : alignement du stock impossible pour %s", config.name)
