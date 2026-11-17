# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        # v9.42 : « inventory_quantity » (quantité COMPTÉE, pas encore
        # appliquée) ne déclenche plus d'envoi. Avant, la saisie d'une
        # quantité dans Odoo lançait la synchro alors que le stock en main
        # n'avait pas encore changé : en mode « les deux sens », la valeur
        # Shopify (souvent 0) était appliquée PAR-DESSUS la saisie, qui se
        # retrouvait enregistrée à 0. L'envoi part quand l'inventaire est
        # appliqué (changement de « quantity »).
        if "quantity" in vals or "reserved_quantity" in vals:
            self._shopify_push_touched_pairs()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        quants = super().create(vals_list)
        if not self.env.context.get("shopify_sync"):
            # Un quant créé avec seulement une quantité comptée (mode
            # inventaire) n'a encore rien changé au stock : pas d'envoi.
            quants.filtered(lambda q: q.quantity or q.reserved_quantity)._shopify_push_touched_pairs()
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
        if config.inventory_master in ("odoo", "both"):
            # Odoo = référence : on n'écrase JAMAIS Odoo avec Shopify ; on
            # aligne Shopify sur Odoo (les articles sans aucun mouvement
            # Odoo sont, eux, importés une première fois depuis Shopify).
            return self.shopify_push_inventory_all(config)
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
            if not location._shopify_is_stock_location():
                # Emplacement en doublon sur le même entrepôt : son stock
                # (mis à 0 par Odoo) ne doit jamais écraser le stock Odoo.
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
                # Correctif : une erreur sur UNE variante (ex : produit non
                # stockable) arrêtait tout l'import du stock.
                try:
                    with self.env.cr.savepoint():
                        variant_link.product_id._shopify_apply_inventory_level(
                            location.warehouse_id,
                            levels_by_item[variant_link.shopify_inventory_item_id],
                            config,
                        )
                    applied += 1
                except Exception as exc:  # noqa: BLE001
                    _logger.exception(
                        "Stock Shopify non appliqué pour %s", variant_link.product_id.display_name
                    )
                    self._shopify_log_inventory_in(
                        config, variant_link.product_id,
                        variant_link.shopify_inventory_item_id, f"Stock Shopify non appliqué : {exc}",
                    )
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
        if not self.is_storable:
            # Odoo ne garde aucune quantité pour un produit non suivi en stock :
            # sans cette case, le stock Shopify ne peut pas être importé.
            variant_link = self._shopify_get_variant_link(config) if config else False
            self._shopify_log_inventory_in(
                config, self, variant_link.shopify_inventory_item_id if variant_link else False,
                f"Stock Shopify ({available}) non importé : le produit n'est pas "
                f"« Suivre l'inventaire » (is_storable) dans Odoo. Cochez cette case "
                f"sur la fiche produit puis relancez « Importer le stock ».",
            )
            return
        self._shopify_lock_stock(self)
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
        ctx = self._shopify_inventory_ctx()
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
        self._shopify_apply_quant(quant, ctx)
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
    # Application d'un ajustement d'inventaire (v9.42)
    # ------------------------------------------------------------------
    @staticmethod
    def _shopify_inventory_ctx():
        # set_inventory_quantity_auto_apply : sans lui, Odoo renvoie une
        # FENÊTRE (conflit d'inventaire « quantité obsolète », produit suivi
        # par lot...) au lieu d'appliquer : l'ajustement n'était pas fait, le
        # stock Odoo restait à 0... et ce 0 repartait vers Shopify.
        return {"shopify_sync": True, "inventory_mode": True, "set_inventory_quantity_auto_apply": True}

    def _shopify_lock_stock(self, product):
        """v9.49 : verrou par produit avant d'ajouter / fixer du stock.
        Deux traitements simultanés (webhook + tâche planifiée, bouton +
        tâche...) voyaient tous les deux le stock Odoo à 0 et ajoutaient
        chacun la quantité Shopify : quantité DOUBLÉE (deux quants créés
        en parallèle, sans conflit). Mettre à jour la ligne du produit
        force PostgreSQL à refuser le 2e traitement (conflit de
        sérialisation) : il est rejoué (requête web) ou repris au passage
        suivant (tâche), et voit alors le stock déjà ajouté."""
        self.env.cr.execute(
            "UPDATE product_product SET write_date = write_date WHERE id = %s", (product.id,)
        )

    def _shopify_apply_quant(self, quant, ctx):
        from odoo.exceptions import UserError
        result = quant.with_context(**ctx).action_apply_inventory()
        if isinstance(result, dict) and result.get("res_model"):
            raise UserError(
                f"Ajustement d'inventaire NON appliqué par Odoo (fenêtre « {result.get('name')} » "
                f"demandée) pour {quant.product_id.display_name}"
            )

    def _shopify_log_inventory_in(self, config, product, item_id, message):
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id if config else False,
                "direction": "in",
                "model_name": "product.product",
                "res_id": product.id,
                "shopify_object_type": "inventory_level",
                "shopify_object_id": item_id or False,
                "state": "error",
                "message": message,
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
        try:
            client.rest_put(
                f"/inventory_items/{int(item_id)}.json",
                {"inventory_item": {"id": int(item_id), "tracked": True}},
            )
        except ShopifyAPIError as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            # L'article n'existe plus sur cette boutique (produit supprimé
            # ou retiré de la boutique) : lien de variante périmé, on le
            # supprime au lieu de renvoyer une erreur à chaque mouvement.
            stale = self.env["shopify.variant.link"].sudo().search(
                [("shopify_inventory_item_id", "=", str(item_id))]
            )
            _logger.info(
                "Article de stock Shopify %s introuvable : %s lien(s) de variante supprimé(s).",
                item_id, len(stale),
            )
            stale.unlink()
            return False
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
            if not location._shopify_is_stock_location():
                # Plusieurs emplacements Shopify sur le même entrepôt Odoo :
                # Shopify additionne les emplacements. Ceux-ci sont mis à 0
                # pour que le total Shopify = stock Odoo (fin du doublon).
                self._shopify_zero_secondary_location(client, location, product, config)
                continue
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

            if config.inventory_master == "shopify" and self.env.context.get("shopify_product_push"):
                # v9.42 : renvoi d'un produit dédié en mode « Shopify fait
                # foi » : le stock du produit principal n'est pas écrasé.
                continue
            variant_link = product._shopify_get_variant_link(config)
            if not variant_link:
                continue  # produit non lié à cette boutique : normal
            if config.inventory_master == "both" and variant_link.shopify_inventory_item_id:
                self._shopify_reconcile_level(client, config, location, product, variant_link)
                continue
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

    # ------------------------------------------------------------------
    # SYNCHRO DANS LES DEUX SENS (Référence du stock = « les deux »)
    # ------------------------------------------------------------------
    @staticmethod
    def _shopify_agreed_get(link, location_id):
        """Dernier stock commun pour l'article Shopify ACTUEL du lien.

        v9.42 : la valeur est liée à l'`inventory_item_id`. Si l'article
        Shopify a changé (variante recréée, liens réassociés), l'ancienne
        valeur ne veut plus rien dire : on la considère absente. Avant,
        elle restait (ex : 5) alors que le nouvel article démarrait à 0
        -> « Shopify a changé 5 -> 0 » -> le stock Odoo était remis à 0."""
        try:
            data = json.loads(link.shopify_stock_agreed or "{}")
        except ValueError:
            data = {}
        if str(data.get("_item") or "") != str(link.shopify_inventory_item_id or ""):
            return None
        value = data.get(str(location_id))
        return int(value) if value is not None else None

    @staticmethod
    def _shopify_agreed_set(link, location_id, qty):
        item = str(link.shopify_inventory_item_id or "")
        try:
            data = json.loads(link.shopify_stock_agreed or "{}")
        except ValueError:
            data = {}
        if str(data.get("_item") or "") != item:
            data = {"_item": item}
        if data.get(str(location_id)) == int(qty):
            return
        data[str(location_id)] = int(qty)
        link.with_context(shopify_sync=True).sudo().write({"shopify_stock_agreed": json.dumps(data)})

    def _shopify_read_available(self, client, location, item_id):
        """Disponible Shopify de l'article sur l'emplacement, ou None si
        l'article n'est pas stocké à cet emplacement (avant : 0, pris pour
        une vraie mise à 0 dans Shopify et recopié dans Odoo)."""
        location_id = getattr(location, "shopify_location_id", location)  # enregistrement ou ID
        levels = client.rest_get(
            "/inventory_levels.json",
            {"inventory_item_ids": str(item_id), "location_ids": location_id},
        ).get("inventory_levels") or []
        if not levels:
            return None
        return int(levels[0].get("available") or 0)

    def _shopify_refresh_recent_orders(self, config):
        """Importe les commandes Shopify modifiées ces dernières minutes,
        pour qu'une VENTE Shopify déjà réservée dans Odoo ne soit pas prise
        pour une correction manuelle de stock (sinon : comptée 2 fois)."""
        if self.env.context.get("shopify_orders_fresh") or not config.sync_orders:
            return
        since = fields.Datetime.now() - timedelta(minutes=30)
        try:
            with self.env.cr.savepoint():
                self.env["sale.order"].sudo().with_context(
                    shopify_orders_fresh=True
                ).shopify_import_all(config, updated_at_min=since)
        except Exception:  # noqa: BLE001
            _logger.exception("Import des commandes récentes impossible (%s)", config.name)

    def _shopify_add_onhand(self, product, warehouse, delta):
        """Ajoute `delta` (positif ou négatif) au stock Odoo de l'entrepôt,
        par un ajustement d'inventaire, SANS renvoi vers Shopify."""
        self._shopify_lock_stock(product)
        Quant = self.env["stock.quant"].sudo()
        quant = Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", warehouse.lot_stock_id.id),
                ("lot_id", "=", False),
                ("owner_id", "=", False),
                ("package_id", "=", False),
            ],
            limit=1,
        )
        ctx = self._shopify_inventory_ctx()
        new_qty = max((quant.quantity if quant else 0.0) + delta, 0.0)
        if quant:
            quant.with_context(**ctx).write({"inventory_quantity": new_qty})
        else:
            quant = Quant.with_context(**ctx).create(
                {"product_id": product.id, "location_id": warehouse.lot_stock_id.id,
                 "inventory_quantity": new_qty}
            )
        self._shopify_apply_quant(quant, ctx)

    def _shopify_import_change(self, config, product, warehouse, location, item_id, delta, target, label):
        """Reporte dans Odoo un changement de stock venu de Shopify, et
        VÉRIFIE qu'il a bien été appliqué. Si Odoo ne l'a pas pris (erreur,
        réservation immédiate, fenêtre de conflit...), on ne renvoie PAS le
        stock Odoo vers Shopify (avant : Odoo restait à 0 et ce 0 écrasait
        quelques secondes plus tard la quantité saisie dans Shopify / par
        l'API) ; l'erreur exacte est écrite dans le journal."""
        before = self._shopify_stock_detail(product, warehouse)
        try:
            with self.env.cr.savepoint():
                self._shopify_add_onhand(product, warehouse, delta)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Stock Shopify non reporté dans Odoo (%s)", product.display_name)
            self._shopify_log_inventory_in(
                config, product, item_id,
                f"{label} : NON reporté dans Odoo ({exc}). Stock Odoo {before}. "
                f"Shopify garde {target} (pas de remise à 0).",
            )
            return False
        after_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
        after = self._shopify_stock_detail(product, warehouse)
        if after_free != target:
            self._shopify_log_inventory_in(
                config, product, item_id,
                f"{label} : reporté dans Odoo ({'+' if delta > 0 else ''}{delta}) mais le disponible "
                f"Odoo vaut {after_free} au lieu de {target}. Avant : {before} ; après : {after}. "
                f"Shopify garde {target} (pas de remise à 0). Vérifiez les réservations / "
                f"livraisons en attente de ce produit dans {warehouse.name}.",
            )
            return False
        self._shopify_log_inventory_in_ok(
            config, product, item_id,
            f"{label}, reporté dans Odoo ({'+' if delta > 0 else ''}{delta} dans {warehouse.name}). "
            f"Stock Odoo : {after}",
        )
        return True

    def _shopify_stock_detail(self, product, warehouse):
        quants = self.env["stock.quant"].sudo().search(
            [("product_id", "=", product.id), ("location_id", "child_of", warehouse.lot_stock_id.id)]
        )
        on_hand = sum(quants.mapped("quantity"))
        reserved = sum(quants.mapped("reserved_quantity"))
        return f"en main {on_hand:g}, réservé {reserved:g}, disponible {on_hand - reserved:g}"

    def _shopify_reconcile_level(self, client, config, location, product, link,
                                 shopify_available=None, shopify_known=False):
        """Synchro dans les deux sens pour UN article sur l'emplacement
        principal : compare le stock disponible Odoo et Shopify au dernier
        stock commun, et reporte le changement du côté qui a bougé.

        Ventes : une commande Shopify baisse le disponible Shopify ET (une
        fois importée et réservée) le disponible Odoo -> les deux côtés ont
        bougé pareil, rien n'est compté deux fois. Les commandes récentes
        sont importées avant de reporter un changement Shopify."""
        product = product.sudo()
        item_id = link.shopify_inventory_item_id
        warehouse = location.warehouse_id
        if not shopify_known and shopify_available is None:
            shopify_available = self._shopify_read_available(client, location, item_id)
        odoo_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
        agreed = self._shopify_agreed_get(link, location.shopify_location_id)

        if shopify_available is None:
            # v9.42 : article pas (encore) stocké sur cet emplacement Shopify
            # (variante recréée, emplacement changé...). Ce n'est PAS une mise
            # à 0 faite dans Shopify : on ne touche pas à Odoo, on rattache
            # l'article à l'emplacement et on y envoie le stock Odoo.
            self._shopify_set_inventory_level(client, location.shopify_location_id, item_id, odoo_free)
            self._shopify_log_inventory(
                config, product, item_id, "success",
                f"Entrepôt {warehouse.name} -> {location.name} : {odoo_free} disponible(s) "
                f"(article rattaché à l'emplacement)",
            )
            self._shopify_agreed_set(link, location.shopify_location_id, odoo_free)
            return

        if shopify_available == odoo_free:
            self._shopify_agreed_set(link, location.shopify_location_id, odoo_free)
            return
        if agreed is None and odoo_free == 0 and shopify_available > 0:
            # v9.42 : premier passage (ou article Shopify changé) avec un
            # stock Odoo VIDE : avant, Shopify était aligné sur Odoo -> le
            # vrai stock Shopify était effacé (remis à 0). On reprend
            # maintenant le stock Shopify dans Odoo.
            self._shopify_refresh_recent_orders(config)
            odoo_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
            if odoo_free == 0:
                if not self._shopify_import_change(
                    config, product, warehouse, location, item_id, shopify_available, shopify_available,
                    f"Stock Shopify ({location.name}) repris dans Odoo (stock Odoo vide, aucun stock commun connu)",
                ):
                    return
                odoo_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
            if shopify_available == odoo_free:
                self._shopify_agreed_set(link, location.shopify_location_id, odoo_free)
                return
        if agreed is not None and shopify_available != agreed:
            # Shopify a changé : on vérifie d'abord que ce n'est pas une
            # vente pas encore importée.
            self._shopify_refresh_recent_orders(config)
            odoo_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
            if shopify_available == odoo_free:
                self._shopify_agreed_set(link, location.shopify_location_id, odoo_free)
                return
            # Le dernier modifié l'emporte : Shopify a bougé depuis le dernier
            # stock commun -> le disponible Odoo devient celui de Shopify.
            # (Les changements Odoo sont envoyés à Shopify en temps réel, et
            # une vente importée est réservée dans Odoo avant cette étape.)
            apply = shopify_available - odoo_free
            if apply:
                if not self._shopify_import_change(
                    config, product, warehouse, location, item_id, apply, shopify_available,
                    f"Stock modifié dans Shopify ({location.name}) : {agreed} -> {shopify_available}",
                ):
                    return  # Shopify garde SA valeur (jamais remis à 0)
                odoo_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
        # Odoo a changé (ou premier passage, ou les deux) : Shopify = Odoo.
        if shopify_available != odoo_free:
            self._shopify_set_inventory_level(client, location.shopify_location_id, item_id, odoo_free)
            self._shopify_log_inventory(
                config, product, item_id, "success",
                f"Entrepôt {warehouse.name} -> {location.name} : {odoo_free} disponible(s)",
            )
        self._shopify_agreed_set(link, location.shopify_location_id, odoo_free)

    def _shopify_log_inventory_in_ok(self, config, product, item_id, message):
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "product.product",
                "res_id": product.id,
                "shopify_object_type": "inventory_level",
                "shopify_object_id": item_id or False,
                "state": "success",
                "message": message,
            }
        )

    def _shopify_merge_other_location(self, client, config, shopify_location_id, label,
                                      warehouse, product, item_id, qty):
        """v9.42 (mode « les deux sens ») : du stock a été mis sur un
        emplacement Shopify qui ne porte PAS le stock Odoo (emplacement en
        doublon, ou emplacement non relié). Avant, il était ignoré puis remis
        à 0 : ce stock était perdu (« je mets le stock par l'API, tout revient
        à 0 »). Maintenant : l'emplacement est remis à 0, la quantité est
        AJOUTÉE au stock Odoo de l'entrepôt, puis renvoyée sur l'emplacement
        principal. Si Shopify refuse la mise à 0, rien n'est ajouté (pas de
        double comptage). Retourne True si la quantité a été reportée."""
        if not warehouse or int(qty or 0) <= 0:
            return False
        # Relecture juste avant d'agir : la tâche planifiée travaille sur des
        # niveaux lus plus tôt ; si le webhook a déjà reporté ce stock,
        # l'emplacement est à 0 et rien n'est ajouté une 2e fois.
        qty = self._shopify_read_available(client, shopify_location_id, item_id) or 0
        if qty <= 0:
            return False
        try:
            client.rest_post(
                "/inventory_levels/set.json",
                {"location_id": int(shopify_location_id), "inventory_item_id": int(item_id), "available": 0},
            )
        except ShopifyAPIError as exc:
            self._shopify_log_inventory(
                config, product, item_id, "error",
                f"{label} garde {qty} en stock (Shopify refuse la mise à 0) : {exc}",
            )
            return False
        before_free = max(self._shopify_available_in_warehouse(product, warehouse), 0)
        if not self._shopify_import_change(
            config, product, warehouse, None, item_id, qty, before_free + qty,
            f"Stock saisi sur {label} ({qty}), à renvoyer sur l'emplacement principal",
        ):
            # Odoo n'a pas pris la quantité : on la remet sur l'emplacement
            # Shopify d'origine au lieu de la perdre.
            try:
                client.rest_post(
                    "/inventory_levels/set.json",
                    {"location_id": int(shopify_location_id), "inventory_item_id": int(item_id), "available": qty},
                )
            except ShopifyAPIError:
                _logger.exception("Stock %s non remis sur %s", qty, label)
            return False
        self._shopify_push_inventory_for_warehouse(product, warehouse)
        return True

    def _shopify_zero_secondary_location(self, client, location, product, config):
        """Met à 0 le stock d'un emplacement Shopify en doublon (même
        entrepôt Odoo qu'un autre emplacement), sans rattacher l'article à
        cet emplacement s'il n'y est pas stocké."""
        item_ids = []
        variant_link = product._shopify_get_variant_link(config)
        if variant_link and variant_link.shopify_inventory_item_id:
            item_ids.append(variant_link.shopify_inventory_item_id)
        item_ids += self.env["shopify.marketplace.variant.link"].sudo().search(
            [
                ("config_id", "=", config.id),
                ("product_id", "=", product.id),
                ("shopify_inventory_item_id", "!=", False),
            ]
        ).mapped("shopify_inventory_item_id")
        for item_id in item_ids:
            try:
                client.rest_post(
                    "/inventory_levels/set.json",
                    {
                        "location_id": int(location.shopify_location_id),
                        "inventory_item_id": int(item_id),
                        "available": 0,
                    },
                )
            except ShopifyAPIError as exc:
                if getattr(exc, "status_code", None) not in (404, 422):
                    self._shopify_log_inventory(config, product, item_id, "error", str(exc))

    def shopify_push_inventory_all(self, config):
        """Aligne le stock Shopify sur le stock Odoo pour toutes les
        variantes liées à cette boutique. Lit d'abord les niveaux Shopify
        (1 appel par tranche de 250 articles) et n'envoie QUE les écarts :
        avant, chaque variante était renvoyée à chaque passage, ce qui
        rendait la tâche planifiée très longue."""
        config.ensure_one()
        locations = config.location_ids.filtered("warehouse_id")
        if not locations:
            _logger.warning(
                "Boutique %s : aucun emplacement Shopify mappé à un entrepôt "
                "Odoo, aucun stock envoyé.", config.name,
            )
            return
        client = config.get_client()
        links = self.env["shopify.variant.link"].sudo().search(
            [("config_id", "=", config.id), ("shopify_inventory_item_id", "!=", False)]
        )
        mp_links = self.env["shopify.marketplace.variant.link"].sudo().search(
            [("config_id", "=", config.id), ("shopify_inventory_item_id", "!=", False)]
        )
        links_by_item = {str(l.shopify_inventory_item_id): l for l in links}
        items = [(l.product_id, l.shopify_inventory_item_id) for l in links] + [
            (l.product_id, l.shopify_inventory_item_id) for l in mp_links
        ]
        for location in locations:
            try:
                levels = client.rest_get_with_pagination(
                    "/inventory_levels.json",
                    params={"location_ids": location.shopify_location_id, "limit": 250},
                    limit_pages=100000,
                )
            except ShopifyAPIError as exc:
                _logger.warning("Lecture du stock Shopify impossible (%s) : %s", location.name, exc)
                continue
            current = {str(l.get("inventory_item_id")): l.get("available") for l in levels}
            Move = self.env["stock.move"].sudo()
            is_primary = location._shopify_is_stock_location()
            for product, item_id in items:
                if not product.active:
                    continue
                shopify_qty = current.get(str(item_id))
                if not is_primary:
                    if (
                        config.inventory_master == "both"
                        and shopify_qty and shopify_qty > 0
                        and str(item_id) in links_by_item
                    ):
                        # v9.42 : stock saisi sur l'emplacement en doublon ->
                        # reporté dans Odoo au lieu d'être effacé.
                        try:
                            with self.env.cr.savepoint():
                                self._shopify_merge_other_location(
                                    client, config, location.shopify_location_id, location.name,
                                    location.warehouse_id, product, item_id, shopify_qty,
                                )
                        except Exception as exc:  # noqa: BLE001
                            self._shopify_log_inventory(config, product, item_id, "error", str(exc))
                        continue
                    # Emplacement en doublon sur le même entrepôt : remis à 0
                    # (seulement si l'article y est stocké avec une quantité).
                    if shopify_qty:
                        try:
                            with self.env.cr.savepoint():
                                client.rest_post(
                                    "/inventory_levels/set.json",
                                    {
                                        "location_id": int(location.shopify_location_id),
                                        "inventory_item_id": int(item_id),
                                        "available": 0,
                                    },
                                )
                                self._shopify_log_inventory(
                                    config, product, item_id, "success",
                                    f"Doublon supprimé : {location.name} remis à 0 "
                                    f"(le stock de l'entrepôt {location.warehouse_id.name} "
                                    f"est porté par un seul emplacement Shopify)",
                                )
                        except ShopifyAPIError as exc:
                            self._shopify_log_inventory(config, product, item_id, "error", str(exc))
                    continue
                # Correctif : un produit qui n'a JAMAIS eu de mouvement de
                # stock dans Odoo (ex : créé depuis Shopify par la synchro
                # « chaque minute ») a 0 dans Odoo. Avant, ce 0 était envoyé
                # et écrasait le vrai stock Shopify. On importe alors le
                # stock Shopify dans Odoo au lieu de l'écraser.
                if (
                    shopify_qty
                    and shopify_qty > 0
                    and not Move.search_count([("product_id", "=", product.id)], limit=1)
                ):
                    try:
                        with self.env.cr.savepoint():
                            product._shopify_apply_inventory_level(
                                location.warehouse_id, shopify_qty, config
                            )
                    except Exception as exc:  # noqa: BLE001
                        self._shopify_log_inventory_in(
                            config, product, item_id, f"Stock Shopify non appliqué : {exc}"
                        )
                    continue
                if config.inventory_master == "both":
                    link = links_by_item.get(str(item_id))
                    if link:
                        try:
                            with self.env.cr.savepoint():
                                self._shopify_reconcile_level(
                                    client, config, location, product, link,
                                    # None = article non stocké sur cet
                                    # emplacement (≠ 0 saisi dans Shopify).
                                    shopify_available=shopify_qty, shopify_known=True,
                                )
                        except Exception as exc:  # noqa: BLE001
                            self._shopify_log_inventory(config, product, item_id, "error", str(exc))
                        continue
                available = max(self._shopify_available_in_warehouse(product, location.warehouse_id), 0)
                if shopify_qty == available:
                    continue
                try:
                    with self.env.cr.savepoint():
                        self._shopify_set_inventory_level(
                            client, location.shopify_location_id, item_id, available
                        )
                        self._shopify_log_inventory(
                            config, product, item_id, "success",
                            f"Écart corrigé : {location.name} = {available} disponible(s)",
                        )
                except ShopifyAPIError as exc:
                    self._shopify_log_inventory(config, product, item_id, "error", str(exc))
        if config.inventory_master in ("odoo", "both"):
            self._shopify_zero_foreign_locations(config, client, items)
        self._shopify_warn_stock_outside_warehouses(config, links)

    def _shopify_warn_stock_outside_warehouses(self, config, links):
        """v9.50 : seul le stock de l'entrepôt RELIÉ à l'emplacement Shopify
        est envoyé. Un stock rangé dans un AUTRE entrepôt Odoo n'est jamais
        envoyé (Shopify reste à 0) alors que la colonne « Disponible »
        d'Odoo (tous entrepôts) l'affiche : on le signale clairement."""
        warehouses = config.location_ids.filtered(
            lambda l: l.warehouse_id and l._shopify_is_stock_location()
        ).warehouse_id
        if not warehouses:
            return
        Quant = self.env["stock.quant"].sudo()
        outside = []
        for link in links:
            quants = Quant.search([
                ("product_id", "=", link.product_id.id),
                ("location_id.usage", "=", "internal"),
                ("quantity", "!=", 0),
            ])
            other = quants.filtered(lambda q: q.location_id.warehouse_id not in warehouses)
            qty = sum(other.mapped("quantity"))
            if qty > 0:
                outside.append(
                    f"{link.product_id.display_name} : {qty:g} dans "
                    + ", ".join(sorted(set(other.mapped("location_id.warehouse_id.name")) or {"?"}))
                )
        if not outside:
            return
        message = (
            f"{len(outside)} produit(s) ont du stock dans un entrepôt Odoo NON relié à Shopify "
            f"(relié : {', '.join(warehouses.mapped('name'))}). Ce stock n'est PAS envoyé à "
            "Shopify. Reliez l'emplacement Shopify au bon entrepôt (boutique > onglet "
            "Emplacements) ou transférez le stock. Ex. : " + " ; ".join(outside[:8])
        )
        SyncLog = self.env["shopify.sync.log"].sudo()
        if not SyncLog.search_count([
            ("config_id", "=", config.id), ("message", "=", message),
            ("create_date", ">=", fields.Datetime.now() - timedelta(hours=6)),
        ]):
            SyncLog.create({
                "config_id": config.id, "direction": "out", "state": "error",
                "shopify_object_type": "inventory_level", "message": message,
            })

    def _shopify_zero_foreign_locations(self, config, client, items):
        """Odoo = référence du stock : le total Shopify doit être égal au
        stock Odoo. Un article peut aussi être stocké sur des emplacements
        Shopify qu'Odoo ne connaît pas (emplacement d'une app : logisticien,
        Etsy/OrderBridge, Amazon...) ou non reliés à un entrepôt. Shopify
        les additionne -> stock en double. On les remet à 0."""
        stock_ids = {
            str(l.shopify_location_id)
            for l in config.location_ids
            if l.warehouse_id and l._shopify_is_stock_location()
        }
        if not stock_ids:
            return
        by_item = {str(item_id): product for product, item_id in items if product.active}
        item_ids = list(by_item)
        # v9.42 : en mode « les deux sens », s'il n'y a qu'UN entrepôt qui
        # porte le stock, le stock trouvé sur un emplacement non relié (ex :
        # emplacement par défaut de Shopify utilisé par un appel API) est
        # reporté dans Odoo au lieu d'être effacé.
        primaries = config.location_ids.filtered(
            lambda l: l.warehouse_id and l._shopify_is_stock_location()
        )
        merge_warehouse = (
            primaries.warehouse_id
            if config.inventory_master == "both" and len(primaries.warehouse_id) == 1
            else False
        )
        main_items = set(
            self.env["shopify.variant.link"].sudo().search(
                [("config_id", "=", config.id), ("shopify_inventory_item_id", "!=", False)]
            ).mapped("shopify_inventory_item_id")
        )
        names = {str(l.shopify_location_id): l.name for l in config.location_ids}
        for start in range(0, len(item_ids), 50):
            chunk = item_ids[start:start + 50]
            try:
                levels = client.rest_get(
                    "/inventory_levels.json",
                    {"inventory_item_ids": ",".join(chunk), "limit": 250},
                ).get("inventory_levels") or []
            except ShopifyAPIError as exc:
                _logger.warning("Lecture des emplacements Shopify impossible : %s", exc)
                continue
            for level in levels:
                location_id = str(level.get("location_id"))
                if location_id in stock_ids or not level.get("available"):
                    continue
                item_id = str(level.get("inventory_item_id"))
                product = by_item.get(item_id)
                if not product:
                    continue
                label = names.get(location_id) or f"emplacement Shopify {location_id}"
                if merge_warehouse and item_id in main_items and int(level.get("available") or 0) > 0:
                    try:
                        with self.env.cr.savepoint():
                            self._shopify_merge_other_location(
                                client, config, location_id, label, merge_warehouse,
                                product, item_id, level.get("available"),
                            )
                    except Exception as exc:  # noqa: BLE001
                        self._shopify_log_inventory(config, product, item_id, "error", str(exc))
                    continue
                try:
                    with self.env.cr.savepoint():
                        client.rest_post(
                            "/inventory_levels/set.json",
                            {
                                "location_id": int(location_id),
                                "inventory_item_id": int(item_id),
                                "available": 0,
                            },
                        )
                        self._shopify_log_inventory(
                            config, product, item_id, "success",
                            f"Doublon supprimé : {label} avait {level.get('available')} "
                            f"en stock en plus du stock Odoo, remis à 0.",
                        )
                except ShopifyAPIError as exc:
                    self._shopify_log_inventory(
                        config, product, item_id, "error",
                        f"{label} garde {level.get('available')} en stock (Shopify refuse "
                        f"la mise à 0, emplacement géré par une app ?) : {exc}",
                    )

