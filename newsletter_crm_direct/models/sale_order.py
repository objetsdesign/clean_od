# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_b2c = fields.Boolean(string='B2C', compute='_compute_is_b2c', store=True)

    @api.depends('name')
    def _compute_is_b2c(self):
        """
        B2C = commandes Amazon  → nom commence par 'OD' sans tiret  (ex: OD0001)
        B2B = commandes manuelles Odoo → nom contient 'OD-'          (ex: OD-0001)
        """
        for order in self:
            name = order.name or ''
            order.is_b2c = name.startswith('OD') and not name.startswith('OD-')

    def action_recompute_is_b2c(self):
        """Recalculer tous les enregistrements existants"""
        all_orders = self.search([])
        for order in all_orders:
            name = order.name or ''
            order.is_b2c = name.startswith('OD') and not name.startswith('OD-')
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        records = super(SaleOrder, self).create(vals_list)

        for record in records:
            record.name = self.env['ir.sequence'].next_by_code('sale.order.b2b') or record.name

        return records

    def _is_amazon_order(self, vals):
        """
        Détecter si une commande vient d'Amazon.
        À adapter selon ton module d'intégration Amazon.
        """
        # Option 1 : via le champ 'origin' (souvent rempli par les connecteurs Amazon)
        origin = (vals.get('origin') or '').lower()
        if 'amazon' in origin:
            return True

        # Option 2 : via marketplace_order_ref (module sale_amazon d'Odoo)
        if vals.get('amazon_order_ref') or vals.get('marketplace_order_ref'):
            return True

        # Option 3 : via l'équipe de vente dédiée Amazon
        # team = self.env['crm.team'].browse(vals.get('team_id'))
        # if team and 'amazon' in (team.name or '').lower():
        #     return True

        return False