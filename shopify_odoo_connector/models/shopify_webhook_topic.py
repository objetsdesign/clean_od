# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifyWebhookTopic(models.Model):
    _name = "shopify.webhook.topic"
    _description = "Référentiel des topics de webhooks Shopify supportés"

    name = fields.Char(required=True)
    topic = fields.Char(required=True)
    description = fields.Char()
