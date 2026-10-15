# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifySyncLog(models.Model):
    _name = "shopify.sync.log"
    _description = "Journal des synchronisations Shopify <-> Odoo"
    _order = "create_date desc"

    config_id = fields.Many2one("shopify.config", required=True, ondelete="cascade")
    direction = fields.Selection(
        [("in", "Shopify -> Odoo"), ("out", "Odoo -> Shopify")], required=True
    )
    model_name = fields.Char(string="Modèle Odoo")
    res_id = fields.Integer(string="ID enregistrement Odoo")
    shopify_object_type = fields.Char(string="Type d'objet Shopify")
    shopify_object_id = fields.Char(string="ID objet Shopify")
    state = fields.Selection(
        [("success", "Succès"), ("error", "Erreur")], required=True, default="success"
    )
    message = fields.Text()
