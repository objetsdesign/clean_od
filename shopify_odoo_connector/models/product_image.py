# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductImage(models.Model):
    _inherit = "product.image"

    shopify_image_id = fields.Char(string="ID image Shopify", copy=False, index=True)
