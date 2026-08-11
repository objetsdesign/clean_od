# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    b2fa_activity_type = fields.Selection([
        ('b2b', 'B2B Classique'),
        ('fund', 'Fund Raising'),
        ('asie', 'Asie'),
    ], string="Activité (Suivi Devis & Commandes)", tracking=True, copy=False,
        help="Classez ce devis/commande pour qu'il soit repris dans le tableau de bord "
             "'Suivi Devis & Commandes'. Laissez vide pour l'exclure de la synchronisation.")

    b2fa_quote_id = fields.Many2one(
        'b2fa.quote', string="Devis (Suivi Devis & Commandes)", copy=False, readonly=True)
    b2fa_order_id = fields.Many2one(
        'b2fa.order', string="Commande (Suivi Devis & Commandes)", copy=False, readonly=True)

    def action_b2fa_sync_now(self):
        """Manual, single-record sync trigger from the sale.order form."""
        self.env['b2fa.sale.sync'].run_sync(sale_orders=self)
        return True
