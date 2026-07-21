# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    # --- Anti-doublons -------------------------------------------------
    shopify_avoid_duplicate_products = fields.Boolean(
        string="Ne pas dupliquer un produit déjà existant dans Odoo",
        config_parameter="shopify_odoo_connector.avoid_duplicate_products",
        default=True,
        help=(
            "Avant de créer un nouveau produit depuis Shopify, recherche un "
            "produit Odoo existant non encore lié à Shopify ayant la même "
            "référence interne (SKU) ou le même code-barres qu'une variante "
            "Shopify, ou à défaut le même nom exact, et le relie à Shopify "
            "au lieu d'en créer un doublon. Ne s'applique qu'aux produits "
            "à variante unique, par prudence."
        ),
    )
    shopify_avoid_duplicate_customers = fields.Boolean(
        string="Ne pas dupliquer un client déjà existant dans Odoo",
        config_parameter="shopify_odoo_connector.avoid_duplicate_customers",
        default=True,
        help=(
            "Avant de créer un nouveau client depuis Shopify, recherche un "
            "contact Odoo existant non encore lié à Shopify ayant le même "
            "email, et le relie à Shopify au lieu d'en créer un doublon."
        ),
    )

    # --- Synchronisation automatique (cron) -----------------------------
    shopify_sync_interval_minutes = fields.Integer(
        string="Fréquence de la synchronisation automatique (minutes)",
        default=15,
        help=(
            "Intervalle de la tâche planifiée qui importe automatiquement "
            "les produits, commandes, clients et le stock modifiés côté "
            "Shopify, en complément (ou en remplacement) des webhooks."
        ),
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        cron = self.env.ref(
            "shopify_odoo_connector.cron_shopify_reconciliation", raise_if_not_found=False
        )
        if cron:
            res["shopify_sync_interval_minutes"] = cron.interval_number
        return res

    def set_values(self):
        super().set_values()
        cron = self.env.ref(
            "shopify_odoo_connector.cron_shopify_reconciliation", raise_if_not_found=False
        )
        if cron and self.shopify_sync_interval_minutes and self.shopify_sync_interval_minutes > 0:
            cron.write(
                {
                    "interval_number": self.shopify_sync_interval_minutes,
                    "interval_type": "minutes",
                    "active": True,
                }
            )

