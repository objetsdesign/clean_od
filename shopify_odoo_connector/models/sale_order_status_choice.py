# -*- coding: utf-8 -*-
"""Statuts de commande « Paiement », « Traitement » et « Livraison » en liste
de choix colorée (même menu que la colonne « Statut »).

Chaque statut affiché est :
* AUTOMATIQUE par défaut : la valeur reçue de Shopify (mise à jour à chaque
  synchronisation) ;
* ou CHOISI À LA MAIN dans la liste : le choix est gardé jusqu'au retour en
  « Automatique (Shopify) ».

Les champs d'origine (shopify_payment_state, shopify_fulfillment_status,
shopify_delivery_status) ne sont jamais modifiés : la synchronisation, les
filtres et les calculs continuent de les utiliser.
"""
from odoo import api, fields, models

from .sale_order import DELIVERY_STATUS_SELECTION, FULFILLMENT_STATUS_SELECTION

PAYMENT_STATE_SELECTION = [
    ("paid", "Payée"),
    ("pending", "En attente"),
    ("authorized", "Autorisée"),
    ("partially_paid", "Partiellement payée"),
    ("partially_refunded", "Remboursée en partie"),
    ("refunded", "Remboursée"),
    ("voided", "Annulée"),
    ("other", "Autre"),
]

# (champ affiché, champ choix manuel, champ Shopify d'origine)
_CHOICES = [
    ("shopify_payment_choice", "shopify_payment_manual", "shopify_payment_state"),
    ("shopify_fulfillment_choice", "shopify_fulfillment_manual", "shopify_fulfillment_status"),
    ("shopify_delivery_choice", "shopify_delivery_manual", "shopify_delivery_status"),
]


class SaleOrderStatusChoice(models.Model):
    _inherit = "sale.order"

    # --- Paiement ---------------------------------------------------------
    shopify_payment_manual = fields.Selection(PAYMENT_STATE_SELECTION, string="Paiement choisi", copy=False)
    shopify_payment_choice = fields.Selection(
        PAYMENT_STATE_SELECTION, string="Paiement Shopify",
        compute="_compute_shopify_choices", inverse="_inverse_shopify_payment_choice", store=True,
    )
    shopify_payment_is_auto = fields.Boolean(compute="_compute_shopify_choices_auto")

    # --- Traitement -------------------------------------------------------
    shopify_fulfillment_manual = fields.Selection(
        FULFILLMENT_STATUS_SELECTION, string="Traitement choisi", copy=False
    )
    shopify_fulfillment_choice = fields.Selection(
        FULFILLMENT_STATUS_SELECTION, string="Traitement Shopify",
        compute="_compute_shopify_choices", inverse="_inverse_shopify_fulfillment_choice", store=True,
    )
    shopify_fulfillment_is_auto = fields.Boolean(compute="_compute_shopify_choices_auto")

    # --- Livraison --------------------------------------------------------
    shopify_delivery_manual = fields.Selection(DELIVERY_STATUS_SELECTION, string="Livraison choisie", copy=False)
    shopify_delivery_choice = fields.Selection(
        DELIVERY_STATUS_SELECTION, string="Livraison Shopify",
        compute="_compute_shopify_choices", inverse="_inverse_shopify_delivery_choice", store=True,
    )
    shopify_delivery_is_auto = fields.Boolean(compute="_compute_shopify_choices_auto")

    @api.depends(
        "shopify_payment_state", "shopify_payment_manual",
        "shopify_fulfillment_status", "shopify_fulfillment_manual",
        "shopify_delivery_status", "shopify_delivery_manual",
    )
    def _compute_shopify_choices(self):
        for order in self:
            for shown, manual, origin in _CHOICES:
                order[shown] = order[manual] or order[origin] or False

    @api.depends("shopify_payment_manual", "shopify_fulfillment_manual", "shopify_delivery_manual")
    def _compute_shopify_choices_auto(self):
        for order in self:
            order.shopify_payment_is_auto = not order.shopify_payment_manual
            order.shopify_fulfillment_is_auto = not order.shopify_fulfillment_manual
            order.shopify_delivery_is_auto = not order.shopify_delivery_manual

    def _shopify_inverse_choice(self, shown, manual, origin):
        for order in self:
            value = order[shown]
            # Même valeur que Shopify = reste en automatique.
            order[manual] = False if (not value or value == order[origin]) else value

    def _inverse_shopify_payment_choice(self):
        self._shopify_inverse_choice(*_CHOICES[0])

    def _inverse_shopify_fulfillment_choice(self):
        self._shopify_inverse_choice(*_CHOICES[1])

    def _inverse_shopify_delivery_choice(self):
        self._shopify_inverse_choice(*_CHOICES[2])

    # Boutons « Automatique (Shopify) » du menu
    def action_shopify_payment_auto(self):
        self.write({"shopify_payment_manual": False})
        return True

    def action_shopify_fulfillment_auto(self):
        self.write({"shopify_fulfillment_manual": False})
        return True

    def action_shopify_delivery_auto(self):
        self.write({"shopify_delivery_manual": False})
        return True
