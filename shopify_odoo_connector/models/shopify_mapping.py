# -*- coding: utf-8 -*-
"""Mapping avancé Shopify <-> Odoo.

Ces modèles permettent de contrôler précisément comment certains éléments
Shopify, qui n'ont pas d'équivalent 1-pour-1 automatique dans Odoo, sont
traduits lors de l'import :

- Les taxes Shopify (tax_lines, avec un titre et un taux) doivent être
  associées à une taxe Odoo (account.tax) précise, notamment quand
  plusieurs taxes Odoo ont le même taux mais un régime différent.
- Les frais de livraison Shopify (shipping_lines, avec un titre libre
  comme "Standard Shipping" ou "Livraison express") doivent être associés
  à un produit Odoo (et éventuellement un mode de livraison / transporteur)
  pour apparaître correctement sur la commande de vente.

Quand aucun mapping n'existe encore pour un titre/taux rencontré à
l'import, une ligne est créée automatiquement avec `auto_created=True` et
une valeur par défaut raisonnable, afin de ne jamais bloquer l'import.
L'utilisateur peut ensuite corriger ce mapping depuis Configuration ->
Mapping, la correction s'appliquant aux imports suivants.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ShopifyTaxMapping(models.Model):
    _name = "shopify.tax.mapping"
    _description = "Correspondance taxe Shopify <-> taxe Odoo"
    _rec_name = "shopify_title"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    shopify_title = fields.Char(
        string="Titre taxe Shopify",
        required=True,
        help="Titre tel qu'envoyé par Shopify dans tax_lines (ex : 'TVA', 'GST').",
    )
    shopify_rate = fields.Float(
        string="Taux Shopify",
        digits=(16, 4),
        help="Taux tel qu'envoyé par Shopify (ex : 0.2 pour 20%).",
    )
    tax_id = fields.Many2one(
        "account.tax", string="Taxe Odoo", required=True,
        domain="[('type_tax_use', '=', 'sale')]",
    )
    auto_created = fields.Boolean(
        default=False,
        string="Créé automatiquement",
        help="Cette correspondance a été créée automatiquement lors d'un import "
             "car aucun mapping n'existait pour ce titre/taux. Vérifiez que la "
             "taxe Odoo sélectionnée est correcte.",
    )

    _sql_constraints = [
        (
            "mapping_uniq",
            "unique(config_id, shopify_title, shopify_rate)",
            "Ce titre de taxe Shopify est déjà mappé pour cette boutique.",
        ),
    ]

    @api.model
    def get_or_create_odoo_tax(self, config, shopify_title, shopify_rate):
        """Retourne la taxe Odoo correspondant à une ligne de taxe Shopify,
        en créant le mapping (et si besoin la taxe) automatiquement s'il
        n'existe pas encore."""
        shopify_title = (shopify_title or "Taxe").strip()
        shopify_rate = round(float(shopify_rate or 0.0), 4)
        mapping = self.search(
            [
                ("config_id", "=", config.id),
                ("shopify_title", "=", shopify_title),
                ("shopify_rate", "=", shopify_rate),
            ],
            limit=1,
        )
        if mapping:
            return mapping.tax_id

        percent = round(shopify_rate * 100, 3)
        Tax = self.env["account.tax"].sudo()
        tax = Tax.search(
            [
                ("type_tax_use", "=", "sale"),
                ("amount_type", "=", "percent"),
                ("amount", "=", percent),
                ("company_id", "=", config.company_id.id),
            ],
            limit=1,
        )
        if not tax:
            tax = Tax.create(
                {
                    "name": f"{shopify_title} ({percent}%) [Shopify]",
                    "amount": percent,
                    "amount_type": "percent",
                    "type_tax_use": "sale",
                    "company_id": config.company_id.id,
                }
            )
            _logger.info(
                "Taxe Odoo créée automatiquement depuis Shopify : %s (%s%%)",
                shopify_title, percent,
            )
        self.sudo().create(
            {
                "config_id": config.id,
                "shopify_title": shopify_title,
                "shopify_rate": shopify_rate,
                "tax_id": tax.id,
                "auto_created": True,
            }
        )
        return tax


class ShopifyShippingMapping(models.Model):
    _name = "shopify.shipping.mapping"
    _description = "Correspondance mode de livraison Shopify <-> produit Odoo"
    _rec_name = "shopify_title"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    shopify_title = fields.Char(
        string="Titre livraison Shopify",
        required=True,
        help="Titre du mode de livraison tel qu'envoyé par Shopify "
             "(ex : 'Standard Shipping', 'Livraison express').",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Produit Odoo (frais de port)",
        required=True,
        domain="[('type', 'in', ('service', 'consu'))]",
    )
    delivery_carrier_id = fields.Many2one(
        "delivery.carrier", string="Transporteur Odoo",
        help="Optionnel : associe ce mode de livraison Shopify à un "
             "transporteur Odoo existant (pour le suivi logistique).",
    )
    auto_created = fields.Boolean(
        default=False,
        string="Créé automatiquement",
        help="Ce mapping a été créé automatiquement lors d'un import avec un "
             "produit générique 'Frais de livraison'. Vous pouvez le "
             "remplacer par un produit ou transporteur plus précis.",
    )

    _sql_constraints = [
        (
            "mapping_uniq",
            "unique(config_id, shopify_title)",
            "Ce mode de livraison Shopify est déjà mappé pour cette boutique.",
        ),
    ]

    @api.model
    def get_or_create_shipping_product(self, config, shopify_title):
        shopify_title = (shopify_title or "Livraison").strip()
        mapping = self.search(
            [("config_id", "=", config.id), ("shopify_title", "=", shopify_title)], limit=1
        )
        if mapping:
            return mapping

        Product = self.env["product.product"].sudo()
        product = Product.search(
            [("default_code", "=", "SHOPIFY_SHIPPING"), ("company_id", "in", [config.company_id.id, False])],
            limit=1,
        )
        if not product:
            product = Product.create(
                {
                    "name": "Frais de livraison (Shopify)",
                    "default_code": "SHOPIFY_SHIPPING",
                    "type": "service",
                    "sale_ok": True,
                    "purchase_ok": False,
                    "invoice_policy": "order",
                    "company_id": False,
                }
            )
            _logger.info("Produit générique de frais de port créé automatiquement.")
        return self.sudo().create(
            {
                "config_id": config.id,
                "shopify_title": shopify_title,
                "product_id": product.id,
                "auto_created": True,
            }
        )
