# -*- coding: utf-8 -*-
"""Différenciation par boutique :
- stock : chaque boutique reçoit son propre entrepôt (la plus ancienne
  garde l'entrepôt existant) ;
- commandes : la boutique est écrite dans le « Document d'origine »
  (ex : « VONROSS #1001 »), visible aussi sur livraisons et factures."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env["shopify.config"].search([("active", "=", True)], order="id asc")
    try:
        configs._shopify_ensure_own_warehouse()
    except Exception:  # noqa: BLE001
        _logger.exception("Création des entrepôts par boutique impossible")
    for config in configs:
        cr.execute(
            """
            UPDATE sale_order
               SET origin = %s || ' #' || shopify_order_number
             WHERE shopify_config_id = %s
               AND shopify_order_number IS NOT NULL
               AND (origin IS NULL OR origin = '')
            """,
            (config.name, config.id),
        )
