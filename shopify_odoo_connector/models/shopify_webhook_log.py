# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifyWebhookLog(models.Model):
    _name = "shopify.webhook.log"
    _description = "Journal des webhooks Shopify reçus"
    _order = "create_date desc"

    config_id = fields.Many2one("shopify.config", required=True, ondelete="cascade")
    topic = fields.Char(required=True)
    shop_domain = fields.Char()
    payload = fields.Text()
    state = fields.Selection(
        [("received", "Reçu"), ("processed", "Traité"), ("error", "Erreur")],
        default="received",
    )
    error_message = fields.Text()
    processing_time = fields.Float(string="Temps de traitement (s)")
