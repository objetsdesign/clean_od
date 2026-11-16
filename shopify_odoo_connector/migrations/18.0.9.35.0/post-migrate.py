# -*- coding: utf-8 -*-
"""v9.35 : nouvelle colonne « Marketplace » sur les commandes (Etsy, Amazon,
TikTok Shop...). On la remplit pour les commandes Shopify déjà importées."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        env["sale.order"].action_shopify_detect_marketplace()
    except Exception:  # noqa: BLE001
        _logger.exception(
            "Shopify v9.35 : détection de la marketplace des commandes existantes impossible "
            "(utilisez Action > « Shopify : détecter la marketplace » sur la liste des commandes)"
        )
