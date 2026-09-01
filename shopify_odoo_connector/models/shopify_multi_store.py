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

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

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
    # Surcharge du titre / de la description PAR BOUTIQUE (ex : Amazon,
    # Etsy...). Le produit Odoo reste UNIQUE (une seule fiche produit,
    # jamais dupliquée) : ces deux champs permettent simplement d'envoyer
    # un texte différent à chaque boutique liée, sans toucher au nom /
    # à la description de la fiche produit elle-même. Si le champ est
    # laissé vide, _shopify_push_one() retombe automatiquement sur le
    # nom / la description de la fiche produit (comportement historique).
    shopify_title_override = fields.Char(
        string="Titre spécifique à cette boutique",
        help=(
            "Titre envoyé UNIQUEMENT à cette boutique/marketplace (ex : "
            "Amazon, Etsy). Laissez vide pour utiliser le nom de la fiche "
            "produit Odoo par défaut. Le produit Odoo reste unique : "
            "seul le texte envoyé à Shopify pour CETTE boutique change."
        ),
    )
    shopify_description_override = fields.Html(
        string="Description spécifique à cette boutique",
        sanitize=False,
        help=(
            "Description (HTML) envoyée UNIQUEMENT à cette boutique/"
            "marketplace. Laissez vide pour utiliser la description de "
            "la fiche produit Odoo par défaut."
        ),
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

    @api.constrains("config_id", "product_tmpl_id")
    def _check_brand_filter(self):
        """Verrou dur : interdit à la base même de créer un lien entre un
        produit Odoo et une boutique Shopify si la marque du produit
        (shopify_vendor) ne respecte pas les filtres de marque de cette
        boutique (export_brand_filter / export_brand_exclude). C'est la
        condition qui empêche, à la source, tout envoi Odoo -> Shopify
        d'une marque non autorisée (ex: autre chose que "Clérieu") — quel
        que soit l'endroit du code qui tenterait de créer ce lien."""
        for link in self:
            if not link.product_tmpl_id._shopify_matches_brand_filter(link.config_id):
                raise ValidationError(
                    _(
                        "Impossible de lier « %(product)s » à la boutique "
                        "« %(shop)s » : sa marque (« %(brand)s ») n'est pas "
                        "autorisée par le filtre de marque de cette "
                        "boutique (« %(filter)s »)."
                    )
                    % {
                        "product": link.product_tmpl_id.display_name,
                        "shop": link.config_id.display_name,
                        "brand": link.product_tmpl_id.shopify_vendor or _("(aucune)"),
                        "filter": link.config_id.export_brand_filter or _("(aucun)"),
                    }
                )

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

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("shopify_sync") and {
            "shopify_title_override",
            "shopify_description_override",
        }.intersection(vals.keys()):
            # Le titre/la description spécifique à CETTE boutique vient de
            # changer : on renvoie uniquement ce produit vers CETTE
            # boutique (les autres boutiques liées ne sont pas concernées).
            for link in self:
                link.product_tmpl_id.with_context(shopify_sync=True)._shopify_push_one(
                    config=link.config_id
                )
        return result


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
