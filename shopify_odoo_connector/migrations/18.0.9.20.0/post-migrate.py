# -*- coding: utf-8 -*-
"""v9.20 : la marque de la boutique est aussi déduite de son nom sans le
mot « Shopify » (« SHOPIFY CLERIEU » -> CLERIEU). On rattache donc les
produits déjà présents dans Odoo à la boutique de leur marque."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env["shopify.config"].search([("active", "=", True)])
    try:
        configs._shopify_check_products_of_my_brand()
    except Exception:  # noqa: BLE001
        _logger.exception("Shopify v9.20 : rattachement des produits à leur boutique impossible")
