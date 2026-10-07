# -*- coding: utf-8 -*-
import logging

from datetime import datetime, timezone

from odoo import api, fields, models

from .shopify_api_client import ShopifyAPIError

_logger = logging.getLogger(__name__)

FINANCIAL_STATUS_MAP = {
    "paid": "paid",
    "partially_paid": "partial",
    "refunded": "refunded",
    "partially_refunded": "partial_refund",
    "pending": "pending",
    "voided": "voided",
}


# Statut de traitement Shopify (champ « fulfillment_status » de la commande)
FULFILLMENT_STATUS_SELECTION = [
    ("unfulfilled", "Non traitée"),
    ("partial", "Partiellement traitée"),
    ("fulfilled", "Traitée (expédiée)"),
    ("restocked", "Réapprovisionnée"),
]

# Statut de livraison Shopify (champ « shipment_status » des expéditions),
# c'est la colonne « Statut de livraison » de l'admin Shopify.
DELIVERY_STATUS_SELECTION = [
    ("shipped", "Expédiée"),
    ("label_purchased", "Étiquette achetée"),
    ("label_printed", "Étiquette imprimée"),
    ("confirmed", "Confirmée"),
    ("carrier_picked_up", "Prise en charge par le transporteur"),
    ("in_transit", "En transit"),
    ("out_for_delivery", "En cours de livraison"),
    ("attempted_delivery", "Tentative de livraison"),
    ("ready_for_pickup", "Prête pour le retrait"),
    ("picked_up", "Retirée"),
    ("delivered", "Livrée"),
    ("failure", "Échec de livraison"),
]
DELIVERY_STATUS_KEYS = {key for key, _label in DELIVERY_STATUS_SELECTION}
FULFILLMENT_STATUS_KEYS = {key for key, _label in FULFILLMENT_STATUS_SELECTION}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_order_id = fields.Char(string="ID commande Shopify", copy=False, index=True)
    shopify_order_number = fields.Char(string="N° commande Shopify")
    shopify_financial_status = fields.Char(string="Statut financier Shopify")
    shopify_fulfillment_status = fields.Selection(
        FULFILLMENT_STATUS_SELECTION,
        string="Statut de traitement Shopify",
        default=False,
        copy=False,
    )
    shopify_delivery_status = fields.Selection(
        DELIVERY_STATUS_SELECTION,
        string="Statut de livraison Shopify",
        copy=False,
        index=True,
        help="Statut de livraison affiché dans Shopify (En transit, Livrée…). "
        "« Expédiée » = commande expédiée sans suivi transporteur.",
    )
    shopify_tracking_company = fields.Char(string="Transporteur Shopify", copy=False)
    shopify_tracking_number = fields.Char(string="N° de suivi Shopify", copy=False)
    shopify_tracking_url = fields.Char(string="Lien de suivi Shopify", copy=False)
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")
    shopify_cancelled_at = fields.Datetime(string="Annulée dans Shopify le", copy=False)
    shopify_confirm_error = fields.Text(
        string="Erreur de confirmation Shopify",
        copy=False,
        readonly=True,
        help="Raison pour laquelle cette commande Shopify n'a pas pu être "
        "confirmée automatiquement (elle sera retentée automatiquement).",
    )

    _sql_constraints = [
        (
            "shopify_order_uniq",
            "unique(shopify_order_id, shopify_config_id)",
            "Cette commande Shopify est déjà importée.",
        ),
    ]

    @staticmethod
    def _shopify_parse_datetime(value):
        """Convertit une date ISO 8601 Shopify (ex: '2026-07-12T03:33:03+02:00')
        en datetime naïf UTC compatible avec les champs Datetime d'Odoo."""
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            _logger.warning("Date Shopify illisible, ignorée : %s", value)
            return False
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config, updated_at_min=None):
        client = config.get_client()
        params = {"limit": 250, "status": "any"}
        if updated_at_min:
            # Heure UTC EXPLICITE : sans fuseau, Shopify lit la date dans le
            # fuseau de la boutique (ex : UTC+2) et ignore alors toutes les
            # modifications des dernières heures.
            params["updated_at_min"] = updated_at_min.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        orders = client.rest_get_with_pagination("/orders.json", params=params)
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    self._shopify_create_or_update_from_data(order, config)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Erreur import commande Shopify %s", order.get("id"))
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "sale.order",
                        "shopify_object_type": "order",
                        "shopify_object_id": str(order.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        config.last_sync_orders = fields.Datetime.now()

    def _shopify_create_or_update_from_data(self, data, config):
        Order = self.env["sale.order"].sudo()
        order = Order.search(
            [
                ("shopify_order_id", "=", str(data["id"])),
                ("shopify_config_id", "=", config.id),
            ],
            limit=1,
        )

        partner = self._shopify_get_or_create_partner(data, config)

        vals = {
            "partner_id": partner.id,
            "shopify_config_id": config.id,
            "shopify_order_id": str(data["id"]),
            "shopify_order_number": str(data.get("order_number") or data.get("name")),
            "shopify_financial_status": data.get("financial_status"),
            "shopify_last_sync": fields.Datetime.now(),
            # Boutique visible partout (commande, bon de livraison, facture) :
            # ex « VONROSS #1001 ».
            "origin": f"{config.name} {data.get('name') or ('#' + str(data.get('order_number') or ''))}".strip(),
        }
        if config.order_team_id:
            vals["team_id"] = config.order_team_id.id
        if config.default_pricelist_id:
            vals["pricelist_id"] = config.default_pricelist_id.id
        if config.default_warehouse_id and (not order or order.state in ("draft", "sent")):
            vals["warehouse_id"] = config.default_warehouse_id.id

        vals.update(self._shopify_prepare_delivery_vals(data))
        vals["shopify_cancelled_at"] = self._shopify_parse_datetime(data.get("cancelled_at"))

        if order:
            order.with_context(shopify_sync=True).write(vals)
        else:
            vals["date_order"] = self._shopify_parse_datetime(data.get("created_at"))
            order = Order.with_context(shopify_sync=True).create(vals)

        self._shopify_sync_order_lines(
            order, data.get("line_items", []), config, data.get("shipping_lines", [])
        )

        # Une commande Shopify est une vente : elle doit TOUJOURS être une
        # commande Odoo (état « Bon de commande »), jamais un devis.
        # - commande annulée dans Shopify -> annulée dans Odoo ;
        # - sinon -> confirmée (si échec : raison affichée sur la commande et
        #   nouvel essai automatique à chaque synchronisation).
        if order.state in ("draft", "sent"):
            if data.get("cancelled_at"):
                order._shopify_cancel_quotation()
            else:
                order._shopify_confirm_order(
                    config, self._shopify_parse_datetime(data.get("created_at"))
                )

        if data.get("financial_status") == "paid":
            order._shopify_register_payment(data, config)

        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "sale.order",
                "res_id": order.id,
                "shopify_object_type": "order",
                "shopify_object_id": str(data["id"]),
                "state": "success",
            }
        )
        return order

    # ------------------------------------------------------------------
    # Statut de traitement / livraison
    # ------------------------------------------------------------------
    @api.model
    def _shopify_prepare_delivery_vals(self, data):
        """Calcule les valeurs de statut d'expédition à partir d'une commande
        Shopify (REST /orders.json : champs « fulfillment_status » et
        « fulfillments »)."""
        fulfillment_status = data.get("fulfillment_status") or "unfulfilled"
        if fulfillment_status not in FULFILLMENT_STATUS_KEYS:
            fulfillment_status = "unfulfilled"

        vals = {
            "shopify_fulfillment_status": fulfillment_status,
            "shopify_delivery_status": False,
            "shopify_tracking_company": False,
            "shopify_tracking_number": False,
            "shopify_tracking_url": False,
        }
        fulfillments = [
            f for f in (data.get("fulfillments") or [])
            if f.get("status") in ("success", "open", "pending", None)
        ]
        if not fulfillments:
            return vals

        # L'expédition la plus récente donne le statut affiché.
        last = max(
            fulfillments,
            key=lambda f: f.get("updated_at") or f.get("created_at") or "",
        )
        shipment_status = last.get("shipment_status")
        vals["shopify_delivery_status"] = (
            shipment_status if shipment_status in DELIVERY_STATUS_KEYS else "shipped"
        )
        tracking_numbers = last.get("tracking_numbers") or []
        tracking_urls = last.get("tracking_urls") or []
        vals["shopify_tracking_company"] = last.get("tracking_company") or False
        vals["shopify_tracking_number"] = (
            last.get("tracking_number") or ", ".join(tracking_numbers) or False
        )
        vals["shopify_tracking_url"] = (
            last.get("tracking_url") or (tracking_urls[0] if tracking_urls else False)
        )
        if fulfillment_status == "unfulfilled":
            # Shopify n'a pas encore recalculé le statut global : au moins une
            # expédition existe, donc la commande est au minimum partielle.
            vals["shopify_fulfillment_status"] = "partial"
        return vals

    def _shopify_update_delivery_status(self, data):
        """Met à jour uniquement les statuts d'expédition / livraison."""
        vals = self._shopify_prepare_delivery_vals(data)
        vals["shopify_last_sync"] = fields.Datetime.now()
        self.with_context(shopify_sync=True).write(vals)

    def _shopify_refresh_delivery_status_from_api(self):
        """Relit la commande dans Shopify et met à jour ses statuts."""
        for order in self.filtered("shopify_order_id"):
            client = order.shopify_config_id.get_client()
            result = client.rest_get(
                f"/orders/{order.shopify_order_id}.json",
                params={"fields": "id,fulfillment_status,fulfillments"},
            )
            data = result.get("order") or {}
            if data:
                order._shopify_update_delivery_status(data)

    def action_shopify_refresh_delivery_status(self):
        """Bouton sur la commande : relire le statut de livraison Shopify."""
        self._shopify_refresh_delivery_status_from_api()
        return True

    def _shopify_confirm_order(self, config, shopify_date=None):
        """Passe une commande Shopify à l'état « Bon de commande » (sale).

        - Confirmation isolée dans un savepoint : un échec n'annule pas
          l'import de la commande.
        - En cas d'échec, la raison est enregistrée sur la commande (bandeau
          rouge + message dans le fil de discussion) et la confirmation est
          retentée automatiquement à chaque synchronisation.
        - Odoo remplace la date de commande par « maintenant » lors de la
          confirmation : on remet la date réelle de la commande Shopify.
        """
        self.ensure_one()
        if self.state not in ("draft", "sent"):
            return True
        shopify_date = shopify_date or self.date_order
        self._shopify_fix_lines_without_product()

        def _confirm(**ctx):
            with self.env.cr.savepoint():
                self.with_context(shopify_sync=True, **ctx).action_confirm()
                vals = {"shopify_confirm_error": False}
                if shopify_date:
                    vals["date_order"] = shopify_date
                self.with_context(shopify_sync=True).write(vals)

        try:
            _confirm()
            return True
        except Exception as first_exc:  # noqa: BLE001
            # Souvent un problème de stock (route / règle d'approvisionnement
            # manquante). La commande Shopify est une vraie vente : on la
            # confirme quand même, sans créer le bon de livraison.
            try:
                _confirm(skip_procurement=True)
                self.message_post(
                    body=(
                        "Commande Shopify confirmée SANS bon de livraison, car "
                        f"Odoo n'a pas pu le créer : {first_exc}"
                    )
                )
                return True
            except Exception:  # noqa: BLE001
                pass
            exc = first_exc
            error = str(exc) or exc.__class__.__name__
            _logger.warning(
                "Impossible de confirmer la commande Shopify %s : %s",
                self.shopify_order_number, error,
            )
            if self.shopify_confirm_error != error:
                # On ne prévient qu'une fois par erreur différente (pas de
                # message répété à chaque synchronisation).
                self.with_context(shopify_sync=True).write({"shopify_confirm_error": error})
                self.message_post(
                    body=(
                        "Cette commande Shopify n'a pas pu être confirmée "
                        f"automatiquement : {error}. Corrigez la cause : la "
                        "confirmation sera retentée automatiquement."
                    )
                )
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "sale.order",
                        "res_id": self.id,
                        "shopify_object_type": "order",
                        "shopify_object_id": self.shopify_order_id,
                        "state": "error",
                        "message": f"Commande restée en devis : {error}",
                    }
                )
            return False

    def _shopify_cancel_quotation(self):
        """Commande annulée dans Shopify : on l'annule dans Odoo (sans
        renvoyer l'annulation vers Shopify)."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.with_context(shopify_sync=True, disable_cancel_warning=True).action_cancel()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Impossible d'annuler la commande Shopify %s", self.shopify_order_number
            )

    @api.model
    def _shopify_get_custom_item_product(self):
        """Produit générique utilisé pour les articles Shopify sans produit
        Odoo correspondant (articles personnalisés des commandes
        provisoires…). Service sans taxe : le prix et les taxes viennent de
        Shopify."""
        Product = self.env["product.product"].sudo().with_context(active_test=False, shopify_sync=True)
        product = Product.search([("default_code", "=", "SHOPIFY-CUSTOM")], limit=1)
        if not product:
            product = Product.create(
                {
                    "name": "Article Shopify personnalisé",
                    "default_code": "SHOPIFY-CUSTOM",
                    "type": "service",
                    "sale_ok": True,
                    "purchase_ok": False,
                    "list_price": 0.0,
                    "taxes_id": [(6, 0, [])],
                    "invoice_policy": "order",
                }
            )
        elif not product.active:
            product.active = True
        return product

    def _shopify_fix_lines_without_product(self):
        """Lignes sans produit (déjà importées) : on leur affecte le produit
        générique en gardant libellé, quantité, prix et taxes Shopify."""
        custom_product = self._shopify_get_custom_item_product()
        for order in self:
            lines = order.order_line.filtered(
                lambda l: not l.display_type and not l.is_downpayment and not l.product_id
            )
            for line in lines:
                line.with_context(shopify_sync=True).write(
                    {
                        "product_id": custom_product.id,
                        "name": line.name,
                        "product_uom_qty": line.product_uom_qty,
                        "price_unit": line.price_unit,
                        "tax_id": [(6, 0, line.tax_id.ids)],
                    }
                )

    @api.model
    def _shopify_confirm_pending_quotations(self, config, limit=200):
        """Filet de sécurité automatique : toute commande Shopify encore en
        devis est confirmée (ou annulée si elle l'est dans Shopify)."""
        orders = self.sudo().search(
            [
                ("shopify_config_id", "=", config.id),
                ("shopify_order_id", "!=", False),
                ("state", "in", ("draft", "sent")),
            ],
            limit=limit,
            order="date_order desc",
        )
        for order in orders:
            if order.shopify_cancelled_at:
                order._shopify_cancel_quotation()
            else:
                order._shopify_confirm_order(config, order.date_order)
        return orders

    def _shopify_get_or_create_partner(self, data, config):
        Partner = self.env["res.partner"].sudo()
        PartnerLink = self.env["shopify.partner.link"].sudo()
        customer_data = data.get("customer")
        if customer_data:
            link = PartnerLink.search(
                [
                    ("shopify_customer_id", "=", str(customer_data["id"])),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
            if link:
                partner = link.partner_id
            else:
                partner = Partner._shopify_create_or_update_from_data(customer_data, config)
            return partner
        # Commande "invité" sans compte client Shopify : on retrouve le
        # client par email / téléphone pour ne pas le dupliquer.
        email = (data.get("email") or data.get("contact_email") or "").strip()
        address = data.get("billing_address") or data.get("shipping_address") or {}
        guest_data = {
            "email": email,
            "phone": data.get("phone") or address.get("phone"),
            "billing_address": address,
        }
        partner = Partner._shopify_find_existing_partner(guest_data, config)
        if partner:
            return partner
        if not email and not guest_data["phone"]:
            partner = Partner.search([("email", "=", "guest@shopify")], limit=1)
            return partner or Partner.create({"name": "guest@shopify", "email": "guest@shopify"})
        name = (
            address.get("name")
            or f"{address.get('first_name') or ''} {address.get('last_name') or ''}".strip()
            or email
            or guest_data["phone"]
        )
        return Partner.with_context(shopify_sync=True).create(
            {"name": name, "email": email or False, "phone": guest_data["phone"] or False,
             "customer_rank": 1}
        )

    def _shopify_sync_order_lines(self, order, line_items, config, shipping_lines=None):
        Line = self.env["sale.order.line"].sudo()
        VariantLink = self.env["shopify.variant.link"].sudo()
        MPVariantLink = self.env["shopify.marketplace.variant.link"].sudo()
        TaxMapping = self.env["shopify.tax.mapping"].sudo()

        for item in line_items:
            variant_link = VariantLink.search(
                [
                    ("shopify_variant_id", "=", str(item.get("variant_id"))),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
            variant = variant_link.product_id
            if not variant and item.get("variant_id"):
                # Commande Etsy importée par OrderBridge sur le produit
                # Shopify DÉDIÉ Etsy : on retrouve la variante Odoo via le
                # lien marketplace (même article Odoo, même stock).
                variant = MPVariantLink.search(
                    [
                        ("shopify_variant_id", "=", str(item.get("variant_id"))),
                        ("config_id", "=", config.id),
                    ],
                    limit=1,
                ).product_id
            if not variant and item.get("sku"):
                # Article non lié : on essaie la référence interne (SKU).
                variant = self.env["product.product"].sudo().search(
                    [("default_code", "=", item["sku"].strip())], limit=1
                )
            if not variant:
                # Article personnalisé (commande provisoire Shopify, article
                # sans variante…) : Odoo refuse de confirmer une commande
                # dont une ligne n'a pas de produit -> produit générique.
                variant = self._shopify_get_custom_item_product()
            existing_line = Line.search(
                [
                    ("order_id", "=", order.id),
                    ("shopify_line_item_id", "=", str(item["id"])),
                ],
                limit=1,
            )
            vals = {
                "order_id": order.id,
                "shopify_line_item_id": str(item["id"]),
                "product_uom_qty": item.get("quantity", 1),
                "price_unit": float(item.get("price") or 0.0),
                "name": item.get("title") or (variant.display_name if variant else "Article Shopify"),
            }
            if variant:
                vals["product_id"] = variant.id

            # --- Mapping avancé des taxes (une ligne Shopify peut avoir
            # plusieurs taxes cumulées : TVA + taxe locale, etc.) ---
            tax_lines = item.get("tax_lines") or []
            if tax_lines:
                tax_ids = [
                    TaxMapping.get_or_create_odoo_tax(
                        config, tax.get("title"), tax.get("rate")
                    ).id
                    for tax in tax_lines
                ]
                vals["tax_id"] = [(6, 0, tax_ids)]

            if existing_line:
                existing_line.with_context(shopify_sync=True).write(vals)
            else:
                Line.with_context(shopify_sync=True).create(vals)

        # --- Frais de livraison (Shopify shipping_lines -> ligne dédiée,
        # via le mapping "shopify.shipping.mapping") ---
        ShippingMapping = self.env["shopify.shipping.mapping"].sudo()
        for shipping in (shipping_lines or []):
            shipping_key = f"shipping-{shipping.get('id') or shipping.get('title')}"
            existing_line = Line.search(
                [
                    ("order_id", "=", order.id),
                    ("shopify_line_item_id", "=", shipping_key),
                ],
                limit=1,
            )
            mapping = ShippingMapping.get_or_create_shipping_product(
                config, shipping.get("title")
            )
            vals = {
                "order_id": order.id,
                "shopify_line_item_id": shipping_key,
                "product_id": mapping.product_id.id,
                "product_uom_qty": 1,
                "price_unit": float(shipping.get("price") or 0.0),
                "name": shipping.get("title") or "Livraison",
            }
            tax_lines = shipping.get("tax_lines") or []
            if tax_lines:
                tax_ids = [
                    TaxMapping.get_or_create_odoo_tax(
                        config, tax.get("title"), tax.get("rate")
                    ).id
                    for tax in tax_lines
                ]
                vals["tax_id"] = [(6, 0, tax_ids)]
            if existing_line:
                existing_line.with_context(shopify_sync=True).write(vals)
            else:
                Line.with_context(shopify_sync=True).create(vals)
            if mapping.delivery_carrier_id and not order.carrier_id:
                order.with_context(shopify_sync=True).write(
                    {"carrier_id": mapping.delivery_carrier_id.id}
                )

    # ------------------------------------------------------------------
    # Paiements
    # ------------------------------------------------------------------
    def _shopify_register_payment(self, data, config):
        """Crée les paiements Odoo correspondant aux transactions Shopify
        réussies de cette commande.

        Important : l'endpoint /orders.json (liste des commandes) n'inclut
        PAS les transactions dans sa réponse — il faut les récupérer via
        l'endpoint dédié /orders/{id}/transactions.json."""
        self.ensure_one()
        client = config.get_client()
        try:
            result = client.rest_get(f"/orders/{data['id']}/transactions.json")
        except ShopifyAPIError as exc:
            _logger.error(
                "Erreur récupération des transactions Shopify pour la commande %s : %s",
                data.get("id"), exc,
            )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "in",
                    "model_name": "account.payment",
                    "res_id": self.id,
                    "shopify_object_type": "transactions",
                    "shopify_object_id": str(data.get("id")),
                    "state": "error",
                    "message": str(exc),
                }
            )
            return
        transactions = result.get("transactions", []) or []
        _logger.info(
            "Commande Shopify %s : %d transaction(s) reçue(s) de l'API.",
            data.get("id"), len(transactions),
        )

        Payment = self.env["account.payment"].sudo()
        created_count = 0
        for transaction in transactions:
            if transaction.get("status") != "success" or transaction.get("kind") not in (
                "sale",
                "capture",
            ):
                _logger.info(
                    "Transaction %s ignorée (status=%s, kind=%s)",
                    transaction.get("id"), transaction.get("status"), transaction.get("kind"),
                )
                continue
            existing = Payment.search(
                [("shopify_transaction_id", "=", str(transaction["id"]))], limit=1
            )
            if existing:
                continue
            try:
                Payment.create(
                    {
                        "partner_id": self.partner_id.id,
                        "amount": float(transaction.get("amount") or 0.0),
                        "payment_type": "inbound",
                        "partner_type": "customer",
                        "shopify_transaction_id": str(transaction["id"]),
                        "shopify_config_id": config.id,
                        "shopify_order_id": self.shopify_order_id,
                        "memo": f"Shopify {self.shopify_order_number}",
                    }
                )
                created_count += 1
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "Erreur création du paiement Odoo pour la transaction Shopify %s",
                    transaction.get("id"),
                )
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "account.payment",
                        "res_id": self.id,
                        "shopify_object_type": "payment",
                        "shopify_object_id": str(transaction.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "account.payment",
                "res_id": self.id,
                "shopify_object_type": "payment",
                "shopify_object_id": str(data.get("id")),
                "state": "success",
                "message": f"{created_count} paiement(s) créé(s) sur {len(transactions)} transaction(s) reçue(s)",
            }
        )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify (statut annulation)
    # ------------------------------------------------------------------
    def action_shopify_cancel(self):
        for order in self:
            if not order.shopify_order_id:
                continue
            client = order.shopify_config_id.get_client()
            try:
                client.rest_post(f"/orders/{order.shopify_order_id}/cancel.json", {})
            except ShopifyAPIError as exc:
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": order.shopify_config_id.id,
                        "direction": "out",
                        "model_name": "sale.order",
                        "res_id": order.id,
                        "shopify_object_type": "order",
                        "shopify_object_id": order.shopify_order_id,
                        "state": "error",
                        "message": str(exc),
                    }
                )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify (nouvelle commande créée dans Odoo)
    # ------------------------------------------------------------------
    def _shopify_push_order_one(self):
        """Crée la commande correspondante côté Shopify pour une commande
        Odoo qui n'existait pas encore là-bas (pas de shopify_order_id).
        Les lignes dont le produit a déjà un shopify_variant_id sont
        envoyées comme des variantes existantes ; les autres (produit
        Odoo pas encore synchronisé, ligne de commentaire/section, frais
        divers) sont envoyées comme des lignes "personnalisées" Shopify
        (title/price/quantity, sans variant_id), ce que l'API Shopify
        accepte nativement."""
        self.ensure_one()
        config = self.shopify_config_id
        if not config:
            return
        client = config.get_client()

        line_items = []
        for line in self.order_line:
            if line.display_type:
                continue
            variant = line.product_id
            item = {
                "quantity": int(line.product_uom_qty) or 1,
                "price": str(line.price_unit),
            }
            variant_link = variant._shopify_get_variant_link(config) if variant else None
            if variant_link and variant_link.shopify_variant_id:
                item["variant_id"] = int(variant_link.shopify_variant_id)
            else:
                item["title"] = line.name or (variant.display_name if variant else "Article")
            line_items.append(item)

        if not line_items:
            return

        payload = {
            "order": {
                "line_items": line_items,
                "financial_status": "paid" if self.invoice_status == "invoiced" else "pending",
                "send_receipt": False,
                "send_fulfillment_receipt": False,
            }
        }
        partner = self.partner_id
        # On rattache un vrai client Shopify (pas juste un email en texte
        # libre) pour que la commande n'apparaisse plus "Aucun client" côté
        # Shopify : si le contact Odoo n'est pas encore lié à un client
        # Shopify, on le pousse d'abord (création), puis on référence son
        # ID Shopify sur la commande.
        if partner and (partner.email or partner.phone) and config.sync_customers:
            partner_link = partner._shopify_get_partner_link(config)
            if not partner_link or not partner_link.shopify_customer_id:
                partner.with_context(shopify_sync=True)._shopify_push_one(config=config)
                partner_link = partner._shopify_get_partner_link(config)
            if partner_link and partner_link.shopify_customer_id:
                payload["order"]["customer"] = {"id": int(partner_link.shopify_customer_id)}
                if partner.email:
                    payload["order"]["email"] = partner.email

        try:
            result = client.rest_post("/orders.json", payload)
            shopify_order = result.get("order", {})
            new_id = shopify_order.get("id")
            if new_id:
                self.with_context(shopify_sync=True).write(
                    {
                        "shopify_order_id": str(new_id),
                        "shopify_order_number": str(
                            shopify_order.get("order_number")
                            or shopify_order.get("name")
                            or new_id
                        ),
                        "shopify_config_id": config.id,
                    }
                )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "sale.order",
                    "res_id": self.id,
                    "shopify_object_type": "order",
                    "shopify_object_id": self.shopify_order_id,
                    "state": "success",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "sale.order",
                    "res_id": self.id,
                    "shopify_object_type": "order",
                    "shopify_object_id": self.shopify_order_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    def action_confirm(self):
        result = super().action_confirm()
        if not self.env.context.get("shopify_sync"):
            default_config = self.env["shopify.config"]._shopify_default_config()
            for order in self:
                if order.shopify_order_id:
                    continue  # déjà une commande Shopify existante, rien à créer
                config = order.shopify_config_id or default_config
                if not config or not config.sync_orders:
                    continue
                if not order.shopify_config_id:
                    order.with_context(shopify_sync=True).shopify_config_id = config.id
                order.with_context(shopify_sync=True)._shopify_push_order_one()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        if not self.env.context.get("shopify_sync"):
            for order in self:
                if order.shopify_order_id:
                    order.with_context(shopify_sync=True).action_shopify_cancel()
        return result
