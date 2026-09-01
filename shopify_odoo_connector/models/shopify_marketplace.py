# -*- coding: utf-8 -*-
"""Différenciation de contenu (titre/description) par marketplace, sur
UNE SEULE boutique Shopify qui centralise plusieurs marketplaces (Amazon,
Etsy, eBay, Cdiscount, ...).

Contexte : Shopify ne permet pas d'avoir deux titres différents sur le
MÊME produit Shopify selon le canal de vente ; le title/body_html du
produit est partagé par toute la boutique. Pour différencier le texte
envoyé à chaque marketplace SANS dupliquer le produit (ni côté Odoo, ni
côté Shopify), ce module :

1. Définit une liste ouverte de marketplaces (`shopify.marketplace`),
   configurée une seule fois (Shopify > Configuration > Marketplaces).
   Avec 2 marketplaces ou 40, le principe est identique : on ajoute une
   ligne dans cette liste, rien d'autre à développer.
2. Sur chaque produit, une ligne par marketplace concernée
   (`shopify.product.marketplace.content`) porte le titre/la description
   propres à cette marketplace. Champ vide = on retombe sur le nom/la
   description générique du produit.
3. Lors de l'export, chaque ligne est envoyée vers Shopify sous forme de
   métachamp (namespace "marketplace_<code>", clés "title"/
   "description") sur le produit Shopify. C'est ensuite à l'intégration
   qui publie réellement sur chaque marketplace (app Shopify dédiée ou
   API externe) de lire le métachamp correspondant à son propre code.
"""
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"[^a-z0-9_]+")


def _slugify_code(value):
    """Transforme un nom libre en code technique utilisable comme
    namespace de métachamp Shopify (minuscules, chiffres, underscores
    uniquement)."""
    value = (value or "").strip().lower()
    value = value.replace("-", "_").replace(" ", "_")
    value = _CODE_RE.sub("", value)
    return value.strip("_") or "marketplace"


class ShopifyMarketplace(models.Model):
    _name = "shopify.marketplace"
    _description = "Marketplace (Amazon, Etsy, eBay, ...)"
    _order = "sequence, name"

    name = fields.Char(required=True, help="Nom affiché, ex : Amazon, Etsy, eBay.")
    code = fields.Char(
        required=True,
        index=True,
        help=(
            "Code technique utilisé comme namespace de métachamp Shopify "
            "(marketplace_<code>). Généré automatiquement à partir du nom "
            "si laissé vide : minuscules, chiffres et underscores "
            "uniquement."
        ),
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Ce code de marketplace est déjà utilisé."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = _slugify_code(vals.get("name"))
            else:
                vals["code"] = _slugify_code(vals["code"])
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals:
            vals["code"] = _slugify_code(vals["code"])
        return super().write(vals)


class ShopifyProductMarketplaceContent(models.Model):
    _name = "shopify.product.marketplace.content"
    _description = "Titre / description spécifique à une marketplace, pour un produit"
    _rec_name = "marketplace_id"

    product_tmpl_id = fields.Many2one(
        "product.template", required=True, ondelete="cascade", string="Produit Odoo"
    )
    marketplace_id = fields.Many2one(
        "shopify.marketplace", required=True, ondelete="restrict", string="Marketplace"
    )
    title_override = fields.Char(
        string="Titre",
        help="Titre envoyé à CETTE marketplace. Laissez vide pour utiliser le nom du produit.",
    )
    description_override = fields.Html(
        string="Description",
        sanitize=False,
        help="Description envoyée à CETTE marketplace. Laissez vide pour utiliser la description du produit.",
    )
    image_override_id = fields.Many2one(
        "product.image",
        string="Image",
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help=(
            "Image envoyée à CETTE marketplace (choisie parmi les photos "
            "déjà présentes dans la galerie du produit). Laissez vide pour "
            "utiliser l'image principale du produit. Utile quand une "
            "marketplace impose un visuel différent (ex : Amazon exige un "
            "fond blanc pur, Etsy accepte des mises en situation)."
        ),
    )
    image_override_preview = fields.Binary(
        string="Aperçu",
        related="image_override_id.image_1920",
        readonly=True,
    )

    _sql_constraints = [
        (
            "product_marketplace_uniq",
            "unique(product_tmpl_id, marketplace_id)",
            "Ce produit a déjà une ligne pour cette marketplace.",
        ),
    ]

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("shopify_sync") and {
            "title_override",
            "description_override",
            "image_override_id",
        }.intersection(vals.keys()):
            # Renvoie le produit (métachamps) dès qu'un titre/description
            # marketplace change, sans attendre une autre modification.
            for content in self:
                content.product_tmpl_id.with_context(
                    shopify_sync=True
                )._shopify_push_one()
        return result
