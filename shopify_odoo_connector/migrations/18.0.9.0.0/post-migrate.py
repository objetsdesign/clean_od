# -*- coding: utf-8 -*-
"""Remplit « Afficher sur les boutiques » :
- les boutiques où le produit est déjà en ligne ;
- pour un produit qui était coché mais pas encore envoyé : la boutique qui
  porte le nom de sa marque (ex : CLERIEU)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    cr.execute("SELECT to_regclass('shopify_display_backup')")
    backup_ids = set()
    if cr.fetchone()[0]:
        cr.execute("SELECT id FROM shopify_display_backup")
        backup_ids = {row[0] for row in cr.fetchall()}
    Template = env["product.template"].with_context(shopify_sync=True)
    Config = env["shopify.config"]
    templates = Template.search(["|", ("shopify_link_ids", "!=", False), ("id", "in", list(backup_ids))])
    for template in templates:
        shops = template.shopify_link_ids.config_id
        if template.id in backup_ids and not shops and template.shopify_vendor:
            shops = Config._shopify_configs_for_brand(template.shopify_vendor)
        if shops:
            template.write({"shopify_target_config_ids": [(4, c.id) for c in shops]})
    cr.execute("DROP TABLE IF EXISTS shopify_display_backup")
    _logger.info("Shopify : boutiques d'affichage renseignées pour %s produits", len(templates))
