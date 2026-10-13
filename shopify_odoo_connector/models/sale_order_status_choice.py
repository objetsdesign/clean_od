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
from odoo import _, api, fields, models
from odoo.exceptions import UserError

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


class SaleOrderOdooStatusChoice(models.Model):
    """« État de la commande » et « Statut de la facture » en liste de choix.

    Ce sont de VRAIS états Odoo : choisir une valeur exécute l'action Odoo
    correspondante (confirmer, annuler, remettre en devis, créer la facture),
    exactement comme les boutons de la commande. Rien n'est seulement
    « affiché » : la liste montre toujours l'état réel.
    """

    _inherit = "sale.order"

    shopify_state_choice = fields.Selection(
        selection=lambda self: self.env["sale.order"]._fields["state"]._description_selection(self.env),
        string="État de la commande",
        compute="_compute_shopify_odoo_choices",
        inverse="_inverse_shopify_state_choice",
    )
    shopify_invoice_choice = fields.Selection(
        selection=lambda self: self.env["sale.order"]._fields["invoice_status"]._description_selection(self.env),
        string="Statut de la facture",
        compute="_compute_shopify_odoo_choices",
        inverse="_inverse_shopify_invoice_choice",
    )

    @api.depends("state", "invoice_status")
    def _compute_shopify_odoo_choices(self):
        for order in self:
            order.shopify_state_choice = order.state
            order.shopify_invoice_choice = order.invoice_status

    def _inverse_shopify_state_choice(self):
        for order in self:
            wanted, current = order.shopify_state_choice, order.state
            if not wanted or wanted == current:
                continue
            if wanted == "sale":
                if current not in ("draft", "sent"):
                    raise UserError(_("Seul un devis peut être confirmé (commande %s).") % order.name)
                order.action_confirm()
            elif wanted == "cancel":
                # Comme le bouton « Annuler », sans la fenêtre d'e-mail.
                order.with_context(disable_cancel_warning=True).action_cancel()
            elif wanted == "draft":
                if current != "cancel" and current != "sent":
                    raise UserError(
                        _("La commande %s est confirmée : annulez-la d'abord pour la remettre en devis.")
                        % order.name
                    )
                order.action_draft()
            elif wanted == "sent":
                if current != "draft":
                    raise UserError(_("Seul un devis peut passer en « Devis envoyé » (commande %s).") % order.name)
                order.write({"state": "sent"})
            else:
                raise UserError(_("Changement d'état non pris en charge pour %s.") % order.name)

    def _inverse_shopify_invoice_choice(self):
        for order in self:
            wanted = order.shopify_invoice_choice
            if not wanted or wanted == order.invoice_status:
                continue
            if wanted == "invoiced":
                if order.invoice_status != "to invoice":
                    raise UserError(_("Rien à facturer sur la commande %s.") % order.name)
                # Facture créée en BROUILLON (à valider ensuite), comme
                # « Créer la facture ».
                order._create_invoices()
            else:
                raise UserError(
                    _(
                        "« %s » est calculé automatiquement par Odoo à partir des factures "
                        "de la commande %s : seul « Entièrement facturé » (création de la "
                        "facture) peut être choisi."
                    )
                    % (dict(self._fields["shopify_invoice_choice"]._description_selection(self.env)).get(wanted, wanted), order.name)
                )
