# -*- coding: utf-8 -*-
"""Statut « tableau de projet » commun à tout le module (v9.7).

Chaque enregistrement Shopify (commande, devis, livraison, facture, produit,
client, paiement, journal, webhook) a un **Statut** :

    Hors piste · À risque · Sur la bonne voie · En pause · Terminé

* Par défaut il est **automatique** : calculé à partir de l'état réel de
  l'enregistrement (voir `_shopify_auto_status` dans chaque modèle).
* Il peut être **choisi à la main** dans les listes (clic sur le badge) ;
  le choix est gardé jusqu'au retour en « Automatique ».
* Les statuts d'origine (Odoo / Shopify) ne sont jamais modifiés : ils
  restent dans leurs propres colonnes.
"""
from odoo import api, fields, models

SHOPIFY_STATUS = [
    ("off", "Hors piste"),
    ("risk", "À risque"),
    ("ok", "Sur la bonne voie"),
    ("pause", "En pause"),
    ("done", "Terminé"),
]


class ShopifyStatusMixin(models.AbstractModel):
    _name = "shopify.status.mixin"
    _description = "Statut Shopify (Hors piste / À risque / Sur la bonne voie / En pause / Terminé)"

    shopify_status_manual = fields.Selection(
        SHOPIFY_STATUS, string="Statut choisi", copy=False,
        help="Statut choisi à la main. Vide = statut automatique.",
    )
    shopify_status = fields.Selection(
        SHOPIFY_STATUS,
        string="Statut",
        compute="_compute_shopify_status",
        inverse="_inverse_shopify_status",
        store=True,
        index=True,
        copy=False,
        help="Automatique (calculé à partir de l'état réel) ou choisi à la main "
        "dans la liste. « En pause » se choisit uniquement à la main.",
    )
    shopify_status_is_auto = fields.Boolean(
        string="Statut automatique", compute="_compute_shopify_status_is_auto"
    )

    @api.depends("shopify_status_manual")
    def _compute_shopify_status_is_auto(self):
        for rec in self:
            rec.shopify_status_is_auto = not rec.shopify_status_manual

    def _shopify_auto_status(self):
        """À redéfinir : statut automatique de `self` (un enregistrement)."""
        return False

    def _shopify_set_status(self):
        for rec in self:
            rec.shopify_status = rec.shopify_status_manual or rec._shopify_auto_status()

    @api.depends("shopify_status_manual")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _inverse_shopify_status(self):
        for rec in self:
            auto = rec._shopify_auto_status()
            value = rec.shopify_status
            rec.shopify_status_manual = False if (not value or value == auto) else value

    def action_shopify_status_auto(self):
        """Repasse le statut en automatique."""
        self.write({"shopify_status_manual": False})
        self._shopify_set_status()
        return True


# ---------------------------------------------------------------------------
# Commandes et devis
# ---------------------------------------------------------------------------
class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "shopify_config_id", "state", "shopify_payment_state",
                 "shopify_delivery_status", "shopify_fulfillment_status")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        if not self.shopify_config_id:
            return False
        if self.state == "cancel" or self.shopify_payment_state in ("refunded", "voided") \
                or self.shopify_delivery_status == "failure":
            return "off"
        if self.shopify_delivery_status in ("delivered", "picked_up"):
            return "done"
        if self.state in ("draft", "sent") or self.shopify_payment_state in (
            "pending", "authorized", "partially_paid", "partially_refunded"
        ):
            return "risk"
        return "ok"


# ---------------------------------------------------------------------------
# Bons de livraison
# ---------------------------------------------------------------------------
class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "state")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        return {
            "cancel": "off",
            "draft": "risk",
            "waiting": "risk",
            "confirmed": "risk",
            "assigned": "ok",
            "done": "done",
        }.get(self.state, False)


# ---------------------------------------------------------------------------
# Factures et avoirs
# ---------------------------------------------------------------------------
class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "state", "payment_state", "move_type")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            return False
        if self.state == "cancel":
            return "off"
        if self.state == "draft":
            return "risk"
        if self.payment_state in ("paid", "reversed"):
            return "done"
        if self.payment_state == "in_payment":
            return "ok"
        return "risk"  # non payée / partiellement payée


# ---------------------------------------------------------------------------
# Paiements Shopify
# ---------------------------------------------------------------------------
class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "state", "shopify_config_id")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        if not self.shopify_config_id:
            return False
        return {
            "canceled": "off", "cancel": "off", "rejected": "off",
            "draft": "risk", "in_process": "ok", "paid": "done",
        }.get(self.state, "ok")


# ---------------------------------------------------------------------------
# Produits
# ---------------------------------------------------------------------------
class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "active", "shopify_link_ids", "shopify_target_config_ids",
                 "shopify_push_pending")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        if not self.shopify_link_ids and not self.shopify_target_config_ids:
            return False  # produit sans rapport avec Shopify
        if not self.active:
            return "done"  # retiré / supprimé côté Shopify
        missing = self.shopify_target_config_ids - self.shopify_link_ids.config_id
        if missing and not self.shopify_push_pending:
            return "off"   # doit être sur une boutique mais n'y est pas
        if self.shopify_push_pending:
            return "risk"  # envoi en attente
        if not self.shopify_target_config_ids:
            return "pause"  # retiré de toutes les boutiques
        return "ok"


class ProductProduct(models.Model):
    _inherit = "product.product"

    shopify_status = fields.Selection(
        related="product_tmpl_id.shopify_status", readonly=False, string="Statut"
    )
    shopify_status_is_auto = fields.Boolean(related="product_tmpl_id.shopify_status_is_auto")

    def action_shopify_status_auto(self):
        return self.product_tmpl_id.action_shopify_status_auto()


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
class ResPartner(models.Model):
    _name = "res.partner"
    _inherit = ["res.partner", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "shopify_partner_link_ids", "active")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        if not self.shopify_partner_link_ids:
            return False
        return "ok" if self.active else "done"


# ---------------------------------------------------------------------------
# Journaux : synchronisations et webhooks
# ---------------------------------------------------------------------------
class ShopifySyncLog(models.Model):
    _name = "shopify.sync.log"
    _inherit = ["shopify.sync.log", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "state")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        return "off" if self.state == "error" else "done"


class ShopifyWebhookLog(models.Model):
    _name = "shopify.webhook.log"
    _inherit = ["shopify.webhook.log", "shopify.status.mixin"]

    @api.depends("shopify_status_manual", "state")
    def _compute_shopify_status(self):
        self._shopify_set_status()

    def _shopify_auto_status(self):
        self.ensure_one()
        return {"error": "off", "received": "risk", "processed": "done"}.get(self.state, False)
