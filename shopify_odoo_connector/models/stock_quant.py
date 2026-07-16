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
        Product = self.env["product.product"].sudo()

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

            levels_by_item = {
                str(level["inventory_item_id"]): level.get("available") or 0
                for level in levels
            }

            variants = Product.search(
                [
                    ("shopify_config_id", "=", config.id),
                    ("shopify_inventory_item_id", "!=", False),
                ]
            )
            for variant in variants:
                if variant.shopify_inventory_item_id not in levels_by_item:
                    continue
                with self.env.cr.savepoint():
                    variant._shopify_apply_inventory_level(
                        location.warehouse_id, levels_by_item[variant.shopify_inventory_item_id]
                    )

    def _shopify_apply_inventory_level(self, warehouse, available):
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
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": self.shopify_config_id.id,
                "direction": "in",
                "model_name": "product.product",
                "res_id": self.id,
                "shopify_object_type": "inventory_level",
                "shopify_object_id": self.shopify_inventory_item_id,
                "state": "success",
                "message": f"Stock importé : {available} dans {warehouse.name}",
            }
        )

    def _shopify_push_inventory_for_warehouse(self, product, warehouse):
        """Calcule la quantité disponible (physique - réservée) du produit
        dans l'entrepôt donné, en agrégeant tous les quants concernés, puis
        pousse le résultat vers Shopify (inventory_levels/set)."""
        product = product.sudo()
        if not product.shopify_config_id or not product.shopify_inventory_item_id:
            return
        if not warehouse or not warehouse.lot_stock_id:
            return

        location = self.env["shopify.location"].sudo().search(
            [
                ("warehouse_id", "=", warehouse.id),
                ("config_id", "=", product.shopify_config_id.id),
            ],
            limit=1,
        )
        if not location:
            return

        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", warehouse.lot_stock_id.id),
            ]
        )
        available = int(sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity")))

        client = product.shopify_config_id.get_client()
        try:
            client.rest_post(
                "/inventory_levels/set.json",
                {
                    "location_id": int(location.shopify_location_id),
                    "inventory_item_id": int(product.shopify_inventory_item_id),
                    "available": max(available, 0),
                },
            )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": product.shopify_config_id.id,
                    "direction": "out",
                    "model_name": "product.product",
                    "res_id": product.id,
                    "shopify_object_type": "inventory_level",
                    "shopify_object_id": product.shopify_inventory_item_id,
                    "state": "success",
                    "message": f"Entrepôt {warehouse.name} : {max(available, 0)} disponible(s)",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": product.shopify_config_id.id,
                    "direction": "out",
                    "model_name": "product.product",
                    "res_id": product.id,
                    "shopify_object_type": "inventory_level",
                    "shopify_object_id": product.shopify_inventory_item_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

