# -*- coding: utf-8 -*-
"""Normalise le « Domaine boutique » des boutiques déjà configurées
(« https://monshop.myshopify.com/ » -> « monshop.myshopify.com ») puis
réinscrit les webhooks : un domaine mal saisi faisait rejeter tous les
webhooks Shopify (dont la suppression de produit)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    Config = env["shopify.config"]
    for config in Config.search([]):
        clean = Config._shopify_normalize_domain(config.shop_url)
        if not clean or clean == config.shop_url:
            continue
        duplicate = Config.search(
            [("id", "!=", config.id), ("shop_url", "=", clean), ("company_id", "=", config.company_id.id)],
            limit=1,
        )
        if duplicate:
            _logger.warning(
                "Domaine de la boutique %s non normalisé (%s déjà utilisé par %s).",
                config.id, clean, duplicate.id,
            )
            continue
        cr.execute("UPDATE shopify_config SET shop_url = %s WHERE id = %s", (clean, config.id))
        _logger.info("Domaine boutique %s : %r -> %r", config.id, config.shop_url, clean)
    env.invalidate_all()
    for config in Config.search([("active", "=", True), ("state", "=", "connected")]):
        try:
            with cr.savepoint():
                config._register_webhooks()
        except Exception:  # noqa: BLE001
            _logger.exception("Réinscription des webhooks impossible pour %s", config.name)
