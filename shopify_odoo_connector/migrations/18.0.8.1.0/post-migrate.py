# -*- coding: utf-8 -*-
"""Confirme tout de suite les commandes Shopify restées en devis (lignes
sans produit corrigées automatiquement)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    SaleOrder = env["sale.order"]
    for config in env["shopify.config"].search([]):
        try:
            SaleOrder._shopify_confirm_pending_quotations(config, limit=None)
        except Exception:  # noqa: BLE001
            _logger.exception("Confirmation des devis Shopify impossible pour %s", config.name)
