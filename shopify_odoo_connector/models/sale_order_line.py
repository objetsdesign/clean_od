# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    shopify_line_item_id = fields.Char(string="ID ligne Shopify", copy=False, index=True)
