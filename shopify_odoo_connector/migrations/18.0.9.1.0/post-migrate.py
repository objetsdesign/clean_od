# -*- coding: utf-8 -*-
"""Le produit technique « Article Shopify personnalisé » (SHOPIFY-CUSTOM)
ne doit apparaître sur aucune boutique : on décoche ses boutiques et on
programme son archivage sur Shopify."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    templates = env["product.template"].search([("default_code", "=", "SHOPIFY-CUSTOM")])
    for template in templates:
        vals = {"shopify_target_config_ids": [(5, 0, 0)], "shopify_vendor": False}
        if template.shopify_link_ids:
            vals.update(
                {
                    "shopify_push_pending": True,
                    "shopify_push_config_ids": [(4, c.id) for c in template.shopify_link_ids.config_id],
                }
            )
        template.with_context(shopify_sync=True).write(vals)
