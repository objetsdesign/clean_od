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
        if config.inventory_master == "odoo":
            # Odoo est la référence du stock : on n'importe JAMAIS le stock
            # Shopify (un stock Shopify à 0 écraserait le vrai stock Odoo).
            _logger.info(
                "Boutique %s : sens du stock Odoo -> Shopify, import du stock "
                "Shopify ignoré.", config.name,
            )
            return
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
    @staticmethod
    def _shopify_stock_override_for(product, content):
        """« Stock affiché » saisi sur une fiche marketplace pour cette
        variante. Renvoie None si aucun stock affiché n'est saisi (= on
        suit le stock réel Odoo).
        - produit à UNE variante : « Stock affiché » de la fiche (onglet
          Général) ;
        - produit à plusieurs variantes : « Stock affiché » de la ligne de
          la variante (onglet Variantes)."""
        if not content:
            return None
        template = product.product_tmpl_id
        if len(template.product_variant_ids) <= 1:
            if content.stock_override:
                return max(int(content.stock_override), 0)
            return None
        line = content.variant_ids.filtered(lambda l: l.product_id == product)[:1]
        if line and line.stock_override:
            return max(int(line.stock_override), 0)
        return None

    def _shopify_real_available(self, product, warehouse):
        """Stock réel disponible (en main - réservé) dans l'entrepôt."""
        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", warehouse.lot_stock_id.id),
            ]
        )
        available = sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity"))
        return max(int(available), 0)

    def _shopify_set_inventory_level(self, config, location, inventory_item_id, quantity):
        """Fixe la quantité « Disponible » d'un article sur un emplacement
        Shopify. Si l'article n'est pas suivi ou pas encore rattaché à
        l'emplacement (erreur 422), on active le suivi / on le rattache,
        puis on réessaie une fois."""
        client = config.get_client()
        payload = {
            "location_id": int(location.shopify_location_id),
            "inventory_item_id": int(inventory_item_id),
            "available": int(quantity),
        }
        try:
            client.rest_post("/inventory_levels/set.json", payload)
            return
        except ShopifyAPIError as exc:
            if getattr(exc, "status_code", None) not in (404, 422):
                raise
            _logger.info(
                "Article %s non suivi / non rattaché à l'emplacement %s : "
                "correction automatique (%s)",
                inventory_item_id, location.name, exc,
            )
        try:
            client.rest_put(
                f"/inventory_items/{int(inventory_item_id)}.json",
                {"inventory_item": {"id": int(inventory_item_id), "tracked": True}},
            )
        except ShopifyAPIError:
            _logger.exception("Activation du suivi de stock impossible (%s)", inventory_item_id)
        try:
            client.rest_post(
                "/inventory_levels/connect.json",
                {
                    "location_id": int(location.shopify_location_id),
                    "inventory_item_id": int(inventory_item_id),
                },
            )
        except ShopifyAPIError:
            # Déjà rattaché : sans importance.
            pass
        client.rest_post("/inventory_levels/set.json", payload)

    def _shopify_log_inventory(self, config, product, item_id, state, message, label="inventory_level"):
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "out",
                "model_name": "product.product",
                "res_id": product.id,
                "shopify_object_type": label,
                "shopify_object_id": item_id,
                "state": state,
                "message": message,
            }
        )

    def _shopify_push_inventory_for_warehouse(self, product, warehouse):
        """Pousse vers Shopify le stock du produit dans cet entrepôt, pour
        CHAQUE boutique dont un emplacement (shopify.location) est mappé à
        cet entrepôt.

        Quantité envoyée :
        - « Stock affiché » de la fiche active (Etsy / Amazon) s'il est
          renseigné (> 0) ;
        - sinon le stock réel Odoo (en main - réservé)."""
        product = product.sudo()
        if not warehouse or not warehouse.lot_stock_id:
            return
        if product.type == "service":
            return

        locations = self.env["shopify.location"].sudo().search(
            [("warehouse_id", "=", warehouse.id)]
        )
        if not locations:
            _logger.info(
                "Stock de %s non envoyé : aucun emplacement Shopify n'est relié "
                "à l'entrepôt %s.", product.display_name, warehouse.name,
            )
            return

        real_available = self._shopify_real_available(product, warehouse)
        template = product.product_tmpl_id
        main_content = template._shopify_main_content()
        MPVariantLink = self.env["shopify.marketplace.variant.link"].sudo()

        for location in locations:
            config = location.config_id

            # Produits Shopify DÉDIÉS (ex : copie Etsy pour OrderBridge) :
            # stock affiché de CETTE marketplace, sinon stock réel.
            for mp_link in MPVariantLink.search(
                [
                    ("config_id", "=", config.id),
                    ("product_id", "=", product.id),
                    ("shopify_inventory_item_id", "!=", False),
                ]
            ):
                content = template.shopify_marketplace_content_ids.filtered(
                    lambda c, m=mp_link.marketplace_id: c.marketplace_id == m
                )[:1]
                override = self._shopify_stock_override_for(product, content)
                qty = real_available if override is None else override
                label = f"inventory_level ({mp_link.marketplace_id.name})"
                try:
                    self._shopify_set_inventory_level(
                        config, location, mp_link.shopify_inventory_item_id, qty
                    )
                    self._shopify_log_inventory(
                        config, product, mp_link.shopify_inventory_item_id, "success",
                        f"{location.name} : {qty} disponible(s)", label,
                    )
                except ShopifyAPIError as exc:
                    self._shopify_log_inventory(
                        config, product, mp_link.shopify_inventory_item_id, "error", str(exc), label,
                    )

            # Produit Shopify principal : stock affiché de la fiche ACTIVE.
            variant_link = product._shopify_get_variant_link(config)
            if variant_link and not variant_link.shopify_inventory_item_id:
                variant_link._shopify_fetch_inventory_item_id()
            if not variant_link or not variant_link.shopify_inventory_item_id:
                self._shopify_log_inventory(
                    config, product, False, "error",
                    "Stock non envoyé : variante non liée à une variante Shopify "
                    "(ID d'inventaire manquant). Relancez « Envoyer vers Shopify » "
                    "sur le produit.",
                )
                continue
            override = self._shopify_stock_override_for(product, main_content)
            qty = real_available if override is None else override
            origin = "stock affiché de la fiche" if override is not None else "stock Odoo"
            try:
                self._shopify_set_inventory_level(
                    config, location, variant_link.shopify_inventory_item_id, qty
                )
                self._shopify_log_inventory(
                    config, product, variant_link.shopify_inventory_item_id, "success",
                    f"{location.name} : {qty} disponible(s) ({origin})",
                )
            except ShopifyAPIError as exc:
                self._shopify_log_inventory(
                    config, product, variant_link.shopify_inventory_item_id, "error", str(exc),
                )
