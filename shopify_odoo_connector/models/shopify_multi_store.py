# -*- coding: utf-8 -*-
"""Liens multi-boutiques.

Avant cette évolution, `product.template`, `product.product` et
`res.partner` portaient chacun un champ unique `shopify_config_id` : un
produit (ou un client) ne pouvait donc être synchronisé que vers UNE seule
boutique Shopify à la fois.

Pour un contexte multi-marques où un même produit (ou un même client) doit
pouvoir exister sur plusieurs boutiques Shopify différentes, ce fichier
introduit trois tables de liaison (une ligne = un lien vers UNE boutique) :

- `shopify.product.link`  : product.template  <-> boutique Shopify
- `shopify.variant.link`  : product.product   <-> boutique Shopify
- `shopify.partner.link`  : res.partner       <-> boutique Shopify

Un même produit/variante/client peut ainsi avoir plusieurs lignes de lien
(une par boutique), chacune avec son propre identifiant Shopify. Créer une
ligne de lien sans identifiant Shopify (config_id renseigné,
shopify_*_id vide) déclenche automatiquement la création de l'objet côté
Shopify (export), ce qui permet de relier un produit/client existant à une
boutique supplémentaire directement depuis l'onglet "Shopify" de sa fiche.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ShopifyProductLink(models.Model):
    _name = "shopify.product.link"
    _description = "Lien produit Odoo <-> produit Shopify (par boutique)"
    _rec_name = "shopify_product_id"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    product_tmpl_id = fields.Many2one(
        "product.template", required=True, ondelete="cascade", string="Produit Odoo"
    )
    shopify_product_id = fields.Char(string="ID produit Shopify", copy=False, index=True)
    shopify_handle = fields.Char(string="Handle Shopify", copy=False)
    shopify_main_image_id = fields.Char(
        string="ID image principale Shopify",
        copy=False,
        help="Sert à ne retélécharger l'image principale que si elle a changé côté Shopify.",
    )
    shopify_main_image_hash = fields.Char(
        string="Empreinte image principale",
        copy=False,
        help="Empreinte (MD5) de la dernière image principale envoyée vers Shopify, "
        "pour ne renvoyer l'image que si elle a réellement changé côté Odoo.",
    )
    last_sync = fields.Datetime(string="Dernière synchro Shopify")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "shopify_product_link_uniq",
            "unique(config_id, shopify_product_id)",
            "Ce produit Shopify est déjà lié pour cette boutique.",
        ),
        (
            "shopify_product_tmpl_config_uniq",
            "unique(config_id, product_tmpl_id)",
            "Ce produit Odoo est déjà lié à cette boutique Shopify.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        links = super().create(vals_list)
        for link in links:
            if not link.shopify_product_id and not self.env.context.get("shopify_sync"):
                # Ligne créée manuellement depuis l'onglet Shopify d'un
                # produit existant, sans ID Shopify : on exporte le produit
                # vers cette boutique supplémentaire (création côté Shopify).
                link.product_tmpl_id.with_context(shopify_sync=True)._shopify_push_one(
                    config=link.config_id
                )
        return links


class ShopifyVariantLink(models.Model):
    _name = "shopify.variant.link"
    _description = "Lien variante Odoo <-> variante Shopify (par boutique)"
    _rec_name = "shopify_variant_id"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    product_id = fields.Many2one(
        "product.product", required=True, ondelete="cascade", string="Variante Odoo"
    )
    shopify_variant_id = fields.Char(string="ID variante Shopify", copy=False, index=True)
    shopify_inventory_item_id = fields.Char(string="ID inventory item Shopify", copy=False)
    shopify_variant_image_id = fields.Char(string="ID photo de variante Shopify", copy=False)
    shopify_variant_image_hash = fields.Char(
        string="Empreinte photo de variante",
        copy=False,
        help="Empreinte (MD5) de la dernière photo de variante envoyée vers Shopify.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "shopify_variant_link_uniq",
            "unique(config_id, shopify_variant_id)",
            "Cette variante Shopify est déjà liée pour cette boutique.",
        ),
        (
            "shopify_variant_product_config_uniq",
            "unique(config_id, product_id)",
            "Cette variante Odoo est déjà liée à cette boutique Shopify.",
        ),
    ]


class ShopifyPartnerLink(models.Model):
    _name = "shopify.partner.link"
    _description = "Lien contact Odoo <-> client Shopify (par boutique)"
    _rec_name = "shopify_customer_id"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", string="Contact Odoo"
    )
    shopify_customer_id = fields.Char(string="ID client Shopify", copy=False, index=True)
    last_sync = fields.Datetime(string="Dernière synchro Shopify")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "shopify_partner_link_uniq",
            "unique(config_id, shopify_customer_id)",
            "Ce client Shopify est déjà lié pour cette boutique.",
        ),
        (
            "shopify_partner_config_uniq",
            "unique(config_id, partner_id)",
            "Ce contact est déjà lié à cette boutique Shopify.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        links = super().create(vals_list)
        for link in links:
            if not link.shopify_customer_id and not self.env.context.get("shopify_sync"):
                link.partner_id.with_context(shopify_sync=True)._shopify_push_one(
                    config=link.config_id
                )
        return links
