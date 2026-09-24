# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

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

    @api.model_create_multi
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

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify (niveaux de stock)
    # ------------------------------------------------------------------
    def _shopify_log_inventory(self, config, product, item_id, state, message, label="inventory_level"):
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "out",
                "model_name": "product.product",
                "res_id": product.id,
                "shopify_object_type": label,
                "shopify_object_id": item_id or False,
                "state": state,
                "message": message,
            }
        )

    def _shopify_ensure_inventory_item_id(self, variant_link):
        """Répare un lien de variante sans `shopify_inventory_item_id`
        (ex : lien créé par un PUT, ou par une ancienne version du module) en
        relisant la variante sur Shopify. Sans cet ID, aucun stock ne peut
        être envoyé."""
        if not variant_link or variant_link.shopify_inventory_item_id:
            return variant_link.shopify_inventory_item_id if variant_link else False
        if not variant_link.shopify_variant_id:
            return False
        try:
            data = variant_link.config_id.get_client().rest_get(
                f"/variants/{variant_link.shopify_variant_id}.json"
            )
        except ShopifyAPIError as exc:
            _logger.warning(
                "Impossible de relire la variante Shopify %s : %s",
                variant_link.shopify_variant_id, exc,
            )
            return False
        item_id = str((data.get("variant") or {}).get("inventory_item_id") or "")
        if item_id:
            variant_link.with_context(shopify_sync=True).write(
                {"shopify_inventory_item_id": item_id}
            )
        return item_id or False

    def _shopify_set_inventory_level(self, client, shopify_location_id, item_id, available):
        """POST /inventory_levels/set.json, avec réparation automatique des
        deux causes de rejet (422) les plus fréquentes :
        - article non suivi (tracked = false) ;
        - article non rattaché (non stocké) à cet emplacement Shopify."""
        payload = {
            "location_id": int(shopify_location_id),
            "inventory_item_id": int(item_id),
            "available": max(int(available), 0),
        }
        try:
            return client.rest_post("/inventory_levels/set.json", payload)
        except ShopifyAPIError as exc:
            if getattr(exc, "status_code", None) not in (404, 422):
                raise
            _logger.info(
                "Shopify a refusé le stock de l'article %s (%s) : activation du "
                "suivi et rattachement à l'emplacement, puis nouvel essai.",
                item_id, exc,
            )
        client.rest_put(
            f"/inventory_items/{int(item_id)}.json",
            {"inventory_item": {"id": int(item_id), "tracked": True}},
        )
        try:
            client.rest_post(
                "/inventory_levels/connect.json",
                {"location_id": int(shopify_location_id), "inventory_item_id": int(item_id)},
            )
        except ShopifyAPIError as exc:
            # Déjà rattaché : Shopify répond 422, ce n'est pas bloquant.
            if getattr(exc, "status_code", None) != 422:
                raise
        return client.rest_post("/inventory_levels/set.json", payload)

    def _shopify_available_in_warehouse(self, product, warehouse):
        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", warehouse.lot_stock_id.id),
            ]
        )
        return int(sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity")))

    def _shopify_push_inventory_for_warehouse(self, product, warehouse):
        """Pousse vers Shopify le stock disponible du produit dans cet
        entrepôt, pour CHAQUE boutique dont un emplacement (shopify.location)
        est mappé à cet entrepôt (un même entrepôt peut servir plusieurs
        boutiques d'une même marque, et un produit peut être lié à
        plusieurs boutiques à la fois).

        Contrairement à l'ancienne version, les cas où RIEN n'est envoyé
        sont désormais tracés dans le journal de synchronisation (au lieu
        d'être ignorés en silence)."""
        product = product.sudo()
        if not warehouse or not warehouse.lot_stock_id:
            return

        locations = self.env["shopify.location"].sudo().search(
            [("warehouse_id", "=", warehouse.id), ("config_id.sync_inventory", "=", True)]
        )
        if not locations:
            # Produit lié à Shopify mais entrepôt non mappé : c'est LA cause
            # la plus fréquente de "le stock ne remonte pas".
            for config in product.shopify_variant_link_ids.config_id.filtered("sync_inventory"):
                self._shopify_log_inventory(
                    config, product, False, "error",
                    f"Stock non envoyé : l'entrepôt Odoo « {warehouse.name} » n'est "
                    f"mappé à aucun emplacement Shopify de la boutique {config.name}. "
                    f"Renseignez « Entrepôt Odoo correspondant » dans les "
                    f"emplacements Shopify de la boutique.",
                )
            return

        available = self._shopify_available_in_warehouse(product, warehouse)

        MPVariantLink = self.env["shopify.marketplace.variant.link"].sudo()
        for location in locations:
            config = location.config_id
            client = config.get_client()
            # Produits Shopify DÉDIÉS (ex : copie Etsy pour OrderBridge) :
            # même stock Odoo que le produit principal, pour ne jamais
            # survendre sur Etsy.
            for mp_link in MPVariantLink.search(
                [
                    ("config_id", "=", config.id),
                    ("product_id", "=", product.id),
                    ("shopify_inventory_item_id", "!=", False),
                ]
            ):
                try:
                    self._shopify_set_inventory_level(
                        client, location.shopify_location_id,
                        mp_link.shopify_inventory_item_id, available,
                    )
                except ShopifyAPIError as exc:
                    self._shopify_log_inventory(
                        config, product, mp_link.shopify_inventory_item_id, "error",
                        str(exc), label=f"inventory_level ({mp_link.marketplace_id.name})",
                    )

            variant_link = product._shopify_get_variant_link(config)
            if not variant_link:
                continue  # produit non lié à cette boutique : normal
            item_id = self._shopify_ensure_inventory_item_id(variant_link)
            if not item_id:
                self._shopify_log_inventory(
                    config, product, variant_link.shopify_variant_id, "error",
                    "Stock non envoyé : ID « inventory item » Shopify introuvable "
                    "pour cette variante (renvoyez le produit vers Shopify).",
                )
                continue
            try:
                self._shopify_set_inventory_level(
                    client, location.shopify_location_id, item_id, available
                )
                self._shopify_log_inventory(
                    config, product, item_id, "success",
                    f"Entrepôt {warehouse.name} -> {location.name} : "
                    f"{max(available, 0)} disponible(s)",
                )
            except ShopifyAPIError as exc:
                self._shopify_log_inventory(config, product, item_id, "error", str(exc))

    def shopify_push_inventory_all(self, config):
        """Envoie le stock Odoo de TOUTES les variantes liées à cette
        boutique, pour chaque entrepôt mappé. Utilisé par le bouton
        « Envoyer le stock vers Shopify » et par la tâche planifiée
        (Odoo = référence du stock)."""
        config.ensure_one()
        warehouses = config.location_ids.warehouse_id
        if not warehouses:
            _logger.warning(
                "Boutique %s : aucun emplacement Shopify mappé à un entrepôt "
                "Odoo, aucun stock envoyé.", config.name,
            )
            return
        products = self.env["shopify.variant.link"].sudo().search(
            [("config_id", "=", config.id)]
        ).product_id
        for product in products:
            for warehouse in warehouses:
                with self.env.cr.savepoint():
                    self._shopify_push_inventory_for_warehouse(product, warehouse)
