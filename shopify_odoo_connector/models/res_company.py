# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    shopify_config_ids = fields.One2many("shopify.config", "company_id")
