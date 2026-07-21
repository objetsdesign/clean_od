# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Ces réglages sont globaux (stockés via ir.config_parameter) et
    # s'appliquent à toutes les boutiques Shopify connectées, à l'image
    # des "General Settings" du connecteur Shopify de référence.
    shopify_use_sales_description = fields.Boolean(
        string="Utiliser la description de vente du produit Odoo",
        config_parameter="shopify_odoo_connector.use_sales_description",
        help=(
            "Si activé, la description de vente Odoo du produit est utilisée "
            "sur les lignes de commande plutôt que la description reçue de "
            "Shopify (qui est au format HTML)."
        ),
    )
    shopify_auto_confirm_orders_default = fields.Boolean(
        string="Confirmer automatiquement les commandes importées (par défaut)",
        config_parameter="shopify_odoo_connector.auto_confirm_orders_default",
        help=(
            "Valeur par défaut proposée à la création d'une nouvelle boutique "
            "Shopify. Peut être surchargée boutique par boutique dans "
            "Configuration > Instances."
        ),
    )
    shopify_log_retention_days = fields.Integer(
        string="Conserver les journaux (jours)",
        config_parameter="shopify_odoo_connector.log_retention_days",
        default=30,
        help="Durée de conservation des journaux de synchronisation et de webhooks.",
    )
