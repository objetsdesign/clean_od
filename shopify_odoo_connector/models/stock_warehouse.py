# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    shopify_location_ids = fields.One2many(
        "shopify.location", "warehouse_id", string="Emplacements Shopify liés"
    )
