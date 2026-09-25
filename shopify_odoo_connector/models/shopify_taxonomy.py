# -*- coding: utf-8 -*-
"""Catégories standard Shopify (taxonomie officielle) copiées dans Odoo,
pour choisir la catégorie d'un produit dans une LISTE identique à celle de
Shopify, au lieu de la saisir en texte libre."""
import gzip
import json
import logging
import time

import requests

from odoo import api, fields, models, _
try:
    from odoo.tools.misc import file_path
except ImportError:  # pragma: no cover
    file_path = None

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

    # ------------------------------------------------------------------
    # Chargement : fichier livré avec le module (taxonomie officielle
    # Shopify, libellés FRANÇAIS identiques à l'admin Shopify), mis à jour
    # chaque mois depuis la source officielle si le serveur y a accès.
    # ------------------------------------------------------------------
    @staticmethod
    def _bundled_rows():
        path = file_path("shopify_odoo_connector/data/shopify_taxonomy_fr.json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)["rows"]

    @staticmethod
    def _download_rows():
        """Taxonomie à jour depuis la source officielle Shopify (même
        format que le fichier livré), ou None si indisponible."""
        try:
            fr = requests.get(TAXONOMY_FR_URL, timeout=120)
            fr.raise_for_status()
            en = requests.get(TAXONOMY_FR_URL.replace("/fr/", "/en/"), timeout=120)
            en.raise_for_status()
            en_names = {
                c["id"]: c["name"] for v in en.json().get("verticals", []) for c in v.get("categories", [])
            }
            rows = []
            for vertical in fr.json().get("verticals", []):
                for c in vertical.get("categories", []):
                    rows.append([
                        c["id"].rsplit("/", 1)[-1], c["name"], c.get("full_name") or c["name"],
                        en_names.get(c["id"], ""), c.get("level") or 0,
                        (c.get("parent_id") or "").rsplit("/", 1)[-1],
                        0 if c.get("children") else 1,
                    ])
            return rows or None
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Mise à jour de la taxonomie Shopify impossible (fichier livré utilisé) : %s", exc)
            return None

    @api.model
    def _shopify_load_rows(self, rows):
        """rows : [code, nom, chemin, nom anglais, niveau, code parent, finale]."""
        prefix = "gid://shopify/TaxonomyCategory/"
        # Deux catégories Shopify peuvent avoir le même libellé français
        # (ex : « Sacs à bandoulière » = Cross Body Bags ET Shoulder Bags) :
        # on ajoute alors le nom anglais pour les distinguer dans la liste.
        counts = {}
        for row in rows:
            counts[row[2]] = counts.get(row[2], 0) + 1
        Category = self.sudo().with_context(active_test=False)
        existing = {c.gid: c for c in Category.search([])}
        to_create = []
        for code, name, full_name, name_en, level, _parent, leaf in rows:
            label = f"{full_name} ({name_en})" if counts[full_name] > 1 and name_en else full_name
            vals = {
                "gid": prefix + code, "name": name, "name_en": name_en,
                "full_name": label, "level": level, "is_leaf": bool(leaf),
            }
            record = existing.get(vals["gid"])
            if not record:
                to_create.append(vals)
            elif any(record[k] != v for k, v in vals.items()):
                record.write(vals)
        if to_create:
            Category.create(to_create)
        by_gid = {c.gid: c for c in Category.search([])}
        children_by_parent = {}
        for row in rows:
            if row[5]:
                children_by_parent.setdefault(prefix + row[5], []).append(by_gid[prefix + row[0]].id)
        for parent_gid, child_ids in children_by_parent.items():
            parent = by_gid.get(parent_gid)
            children = Category.browse(child_ids).filtered(lambda c, p=parent: c.parent_id != p)
            if parent and children:
                children.write({"parent_id": parent.id})
        # Fiches déjà configurées (ancien champ texte) : rattachées à la liste.
        Content = self.env["shopify.product.marketplace.content"].sudo()
        for content in Content.search(
            [("shopify_category_gid", "!=", False), ("shopify_category_id", "=", False)]
        ):
            record = by_gid.get(content.shopify_category_gid)
            if record:
                content.with_context(shopify_sync=True).write({"shopify_category_id": record.id})
        _logger.info("Taxonomie Shopify : %d catégories (%d nouvelles).", len(rows), len(to_create))
        return len(rows)

    @api.model
    def shopify_load_taxonomy(self, config=None, download=False):
        rows = (self._download_rows() if download else None) or self._bundled_rows()
        return self._shopify_load_rows(rows)

    @api.model
    def _shopify_trigger_taxonomy_load(self):
        cron = self.env.ref("shopify_odoo_connector.cron_shopify_load_taxonomy", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def cron_load_taxonomy(self):
        try:
            self.shopify_load_taxonomy(download=True)
        except Exception:  # noqa: BLE001
            _logger.exception("Chargement de la taxonomie Shopify impossible")
