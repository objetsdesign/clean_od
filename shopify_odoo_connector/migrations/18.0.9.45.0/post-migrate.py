# -*- coding: utf-8 -*-
"""v9.45 : rattache à leur boutique les produits trouvés par SKU dans des
commandes Shopify importées (avant : « Pas encore sur Shopify », non comptés,
stock jamais synchronisé)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

QUERY = """query($q: String!) { productVariants(first: 5, query: $q) { nodes {
  id sku inventoryItem { id } product { id } } } }"""


def _num(gid):
    return str(gid or "").rsplit("/", 1)[-1]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    SaleOrder = env["sale.order"].sudo()
    VariantLink = env["shopify.variant.link"].sudo()
    for config in env["shopify.config"].sudo().search([("state", "=", "connected")]):
        lines = env["sale.order.line"].sudo().search([
            ("order_id.shopify_config_id", "=", config.id),
            ("product_id.default_code", "!=", False),
        ])
        linked = set(VariantLink.search([("config_id", "=", config.id)]).mapped("product_id").ids)
        variants = lines.mapped("product_id").filtered(lambda v: v.id not in linked)
        fixed = 0
        for variant in variants:
            sku = (variant.default_code or "").strip()
            try:
                data = config.get_client().graphql(QUERY, variables={"q": f'sku:"{sku}"'})
                nodes = [n for n in ((data or {}).get("productVariants") or {}).get("nodes") or []
                         if (n.get("sku") or "").strip() == sku]
                if len(nodes) != 1:
                    continue  # introuvable ou SKU en double : on ne devine pas
                node = nodes[0]
                item = {"variant_id": _num(node["id"]), "product_id": _num(node["product"]["id"]), "sku": sku}
                with cr.savepoint():
                    SaleOrder._shopify_link_variant_from_order_item(variant, item, config)
                if VariantLink.search_count([("config_id", "=", config.id), ("product_id", "=", variant.id)]):
                    fixed += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Shopify v9.45 : rattachement impossible pour %s", sku)
        _logger.info("Shopify v9.45 : %s produit(s) rattaché(s) à %s", fixed, config.name)
