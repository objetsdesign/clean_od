# -*- coding: utf-8 -*-
"""Catégories standard Shopify (taxonomie officielle) copiées dans Odoo,
pour choisir la catégorie d'un produit dans une LISTE identique à celle de
Shopify, au lieu de la saisir en texte libre."""
import logging
import time

import requests

from odoo import api, fields, models, _

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)

# Libellés français officiels publiés par Shopify (même identifiants que
# l'API). Utilisés en complément : si le fichier est inaccessible, on garde
# les libellés renvoyés par l'API.
TAXONOMY_FR_URL = (
    "https://raw.githubusercontent.com/Shopify/product-taxonomy/main/dist/fr/categories.json"
)

TAXONOMY_QUERY = """
query($after: String, $of: ID) {
  taxonomy {
    categories(first: 250, after: $after, descendantsOf: $of) {
      nodes { id name fullName isLeaf level parentId }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
TAXONOMY_ROOT_QUERY = """
query($after: String) {
  taxonomy {
    categories(first: 250, after: $after) {
      nodes { id name fullName isLeaf level parentId }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class ShopifyTaxonomyCategory(models.Model):
    _name = "shopify.taxonomy.category"
    _description = "Catégorie standard Shopify (taxonomie)"
    _rec_name = "full_name"
    _rec_names_search = ["full_name", "name", "name_en"]
    _order = "full_name"

    gid = fields.Char(string="ID Shopify", required=True, index=True)
    name = fields.Char(string="Nom", required=True)
    name_en = fields.Char(string="Nom (anglais)")
    full_name = fields.Char(string="Catégorie", required=True, index=True)
    parent_id = fields.Many2one("shopify.taxonomy.category", ondelete="set null", index=True)
    level = fields.Integer()
    is_leaf = fields.Boolean(string="Catégorie finale")

    _sql_constraints = [("gid_uniq", "unique(gid)", "Catégorie Shopify déjà importée.")]

    # ------------------------------------------------------------------
    @staticmethod
    def _graphql(client, query, variables):
        """GraphQL avec attente automatique si Shopify limite le débit
        (erreur THROTTLED, renvoyée avec un statut 200)."""
        for attempt in range(6):
            try:
                return client.graphql(query, variables=variables)
            except ShopifyAPIError as exc:
                if "THROTTLED" not in str(exc) or attempt == 5:
                    raise
                time.sleep(2 * (attempt + 1))
        return {}

    def _fetch_all(self, client, query, variables):
        nodes, after = [], None
        while True:
            data = self._graphql(client, query, dict(variables, after=after))
            page = ((data or {}).get("taxonomy") or {}).get("categories") or {}
            nodes += page.get("nodes") or []
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return nodes
            after = info.get("endCursor")

    @staticmethod
    def _fetch_french_labels():
        """{gid: (nom, chemin complet)} en français, ou {} si indisponible."""
        try:
            response = requests.get(TAXONOMY_FR_URL, timeout=60)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Libellés français de la taxonomie Shopify indisponibles : %s", exc)
            return {}
        labels = {}
        for vertical in data.get("verticals") or []:
            for cat in vertical.get("categories") or []:
                if cat.get("id") and cat.get("name"):
                    labels[cat["id"]] = (cat["name"], cat.get("full_name") or cat["name"])
        return labels

    @api.model
    def shopify_load_taxonomy(self, config):
        """Charge (ou met à jour) toute la taxonomie Shopify dans Odoo."""
        client = config.get_client()
        roots = self._fetch_all(client, TAXONOMY_ROOT_QUERY, {})
        nodes = list(roots)
        for root in roots:
            nodes += self._fetch_all(client, TAXONOMY_QUERY, {"of": root["id"]})
        if not nodes:
            raise ShopifyAPIError("Shopify n'a renvoyé aucune catégorie.")
        french = self._fetch_french_labels()

        existing = {c.gid: c for c in self.sudo().search([])}
        to_create = []
        for node in nodes:
            name, full_name = french.get(node["id"], (node.get("name"), node.get("fullName")))
            vals = {
                "gid": node["id"],
                "name": name or node["id"],
                "name_en": node.get("name"),
                "full_name": full_name or name or node["id"],
                "level": node.get("level") or 0,
                "is_leaf": bool(node.get("isLeaf")),
            }
            record = existing.get(node["id"])
            if record:
                if any(record[k] != v for k, v in vals.items()):
                    record.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            self.sudo().create(to_create)
        # Parents, une fois toutes les catégories présentes.
        by_gid = {c.gid: c.id for c in self.sudo().search([])}
        for node in nodes:
            parent = by_gid.get(node.get("parentId"))
            record = self.sudo().browse(by_gid[node["id"]])
            if (record.parent_id.id or False) != (parent or False):
                record.parent_id = parent
        # Fiches déjà configurées (ancien champ texte) : rattachées à la liste.
        Content = self.env["shopify.product.marketplace.content"].sudo()
        for content in Content.search(
            [("shopify_category_gid", "!=", False), ("shopify_category_id", "=", False)]
        ):
            if content.shopify_category_gid in by_gid:
                content.with_context(shopify_sync=True).write(
                    {"shopify_category_id": by_gid[content.shopify_category_gid]}
                )
        _logger.info("Taxonomie Shopify : %d catégories chargées (%d nouvelles).", len(nodes), len(to_create))
        return len(nodes)

    @api.model
    def _shopify_trigger_taxonomy_load(self):
        cron = self.env.ref("shopify_odoo_connector.cron_shopify_load_taxonomy", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def cron_load_taxonomy(self):
        config = self.env["shopify.config"].sudo().search([("state", "=", "connected")], limit=1)
        if not config:
            return
        try:
            self.shopify_load_taxonomy(config)
        except Exception:  # noqa: BLE001
            _logger.exception("Chargement de la taxonomie Shopify impossible")
