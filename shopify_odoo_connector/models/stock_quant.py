# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        if "quantity" in vals or "inventory_quantity" in vals or "reserved_quantity" in vals:
            self._shopify_push_touched_pairs()
        return result

    def create(self, vals_list):
        quants = super().create(vals_list)
        if not self.env.context.get("shopify_sync"):
            quants._shopify_push_touched_pairs()
        return quants

    def _shopify_push_touched_pairs(self):
        """Regroupe les quants par (produit, entrepôt) et ne pousse qu'un seul
        appel API par combinaison, même si plusieurs quants/lots sont touchés
        en même temps (ex: transfert avec plusieurs numéros de série)."""
        seen = set()
        for quant in self:
            product = quant.product_id
            warehouse = quant.location_id.warehouse_id
            if not product or not warehouse:
                continue
            key = (product.id, warehouse.id)
            if key in seen:
                continue
            seen.add(key)
            self.env["product.product"].sudo()._shopify_push_inventory_for_warehouse(
                product, warehouse
            )


class ProductProductStockSync(models.Model):
    _inherit = "product.product"

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo (niveaux de stock)
    # ------------------------------------------------------------------
    def shopify_import_inventory_levels(self, config):
        """Récupère les quantités disponibles actuelles sur Shopify pour
        chaque emplacement mappé à un entrepôt, et les applique dans Odoo
        sous forme d'ajustement d'inventaire (crée les mouvements de stock
        nécessaires pour que la quantité en main corresponde à Shopify)."""
        client = config.get_client()
        VariantLink = self.env["shopify.variant.link"].sudo()

        if not config.location_ids:
            _logger.warning(
                "Aucun emplacement Shopify trouvé pour la boutique %s : "
                "utilisez le bouton 'Resynchroniser les emplacements'.",
                config.name,
            )
            return

        for location in config.location_ids:
            if not location.warehouse_id:
                _logger.info(
                    "Emplacement Shopify %s non mappé à un entrepôt Odoo, ignoré.",
                    location.name,
                )
                continue
            try:
                levels = client.rest_get_with_pagination(
                    "/inventory_levels.json",
                    params={"location_ids": location.shopify_location_id, "limit": 250},
                )
            except ShopifyAPIError as exc:
                _logger.error(
                    "Erreur récupération des niveaux de stock Shopify (emplacement %s) : %s",
                    location.name, exc,
                )
                continue

            _logger.info(
                "Emplacement %s : %d niveau(x) de stock récupéré(s) depuis Shopify.",
                location.name, len(levels),
            )
            levels_by_item = {
                str(level["inventory_item_id"]): level.get("available") or 0
                for level in levels
            }

            variant_links = VariantLink.search(
                [
                    ("config_id", "=", config.id),
                    ("shopify_inventory_item_id", "!=", False),
                ]
            )
            _logger.info(
                "%d variante(s) Odoo liée(s) à Shopify pour cette boutique.",
                len(variant_links),
            )
            applied = 0
            for variant_link in variant_links:
                if variant_link.shopify_inventory_item_id not in levels_by_item:
                    continue
                with self.env.cr.savepoint():
                    variant_link.product_id._shopify_apply_inventory_level(
                        location.warehouse_id,
                        levels_by_item[variant_link.shopify_inventory_item_id],
                        config,
                    )
                applied += 1
            _logger.info(
                "Import stock terminé pour %s : %d variante(s) mise(s) à jour.",
                location.name, applied,
            )

    def _shopify_apply_inventory_level(self, warehouse, available, config=None):
        """Applique une quantité disponible (venant de Shopify) sur
        l'emplacement de stock principal de l'entrepôt, via un ajustement
        d'inventaire standard Odoo (crée un mouvement si nécessaire)."""
        self.ensure_one()
        if not warehouse or not warehouse.lot_stock_id:
            return
        Quant = self.env["stock.quant"].sudo()
        quant = Quant.search(
            [
                ("product_id", "=", self.id),
                ("location_id", "=", warehouse.lot_stock_id.id),
                ("lot_id", "=", False),
                ("owner_id", "=", False),
                ("package_id", "=", False),
            ],
            limit=1,
        )
        ctx = {"shopify_sync": True, "inventory_mode": True}
        if quant:
            quant.with_context(**ctx).write({"inventory_quantity": available})
        else:
            quant = Quant.with_context(**ctx).create(
                {
                    "product_id": self.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "inventory_quantity": available,
                }
            )
        quant.with_context(**ctx).action_apply_inventory()
        variant_link = self._shopify_get_variant_link(config) if config else self.env["shopify.variant.link"]
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id if config else False,
                "direction": "in",
                "model_name": "product.product",
                "res_id": self.id,
                "shopify_object_type": "inventory_level",
                "shopify_object_id": variant_link.shopify_inventory_item_id if variant_link else False,
                "state": "success",
                "message": f"Stock importé : {available} dans {warehouse.name}",
            }
        )

    def _shopify_push_inventory_for_warehouse(self, product, warehouse):
        """Pousse vers Shopify le stock disponible du produit dans cet
        entrepôt, pour CHAQUE boutique dont un emplacement (shopify.location)
        est mappé à cet entrepôt (un même entrepôt peut servir plusieurs
        boutiques d'une même marque, et un produit peut être lié à
        plusieurs boutiques à la fois)."""
        product = product.sudo()
        if not warehouse or not warehouse.lot_stock_id:
            return

        locations = self.env["shopify.location"].sudo().search(
            [("warehouse_id", "=", warehouse.id)]
        )
        if not locations:
            return

        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", warehouse.lot_stock_id.id),
            ]
        )
        available = int(sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity")))

        for location in locations:
            config = location.config_id
            variant_link = product._shopify_get_variant_link(config)
            if not variant_link or not variant_link.shopify_inventory_item_id:
                continue
            client = config.get_client()
            try:
                client.rest_post(
                    "/inventory_levels/set.json",
                    {
                        "location_id": int(location.shopify_location_id),
                        "inventory_item_id": int(variant_link.shopify_inventory_item_id),
                        "available": max(available, 0),
                    },
                )
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "out",
                        "model_name": "product.product",
                        "res_id": product.id,
                        "shopify_object_type": "inventory_level",
                        "shopify_object_id": variant_link.shopify_inventory_item_id,
                        "state": "success",
                        "message": f"Entrepôt {warehouse.name} : {max(available, 0)} disponible(s)",
                    }
                )
            except ShopifyAPIError as exc:
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "out",
                        "model_name": "product.product",
                        "res_id": product.id,
                        "shopify_object_type": "inventory_level",
                        "shopify_object_id": variant_link.shopify_inventory_item_id,
                        "state": "error",
                        "message": str(exc),
                    }
                )

