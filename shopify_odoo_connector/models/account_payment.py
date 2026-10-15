# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_transaction_id = fields.Char(string="ID transaction Shopify", copy=False, index=True)
    shopify_order_id = fields.Char(string="ID commande Shopify")
