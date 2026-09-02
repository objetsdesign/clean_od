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
    image_override = fields.Binary(
        string="Image",
        attachment=True,
        help=(
            "Image envoyée à CETTE marketplace (upload direct, indépendant "
            "de la galerie du produit). Laissez vide pour utiliser l'image "
            "principale du produit. Utile quand une marketplace impose un "
            "visuel différent (ex : Amazon exige un fond blanc pur, Etsy "
            "accepte des mises en situation)."
        ),
    )
    image_override_filename = fields.Char(string="Nom du fichier")

    def _shopify_marketplace_image_url(self):
        """URL web Odoo de l'image marketplace (champ binaire stocké en
        pièce jointe), envoyée comme métachamp `image_url` (namespace
        `marketplace_<code>`) sur le produit Shopify pour cette
        marketplace. Comme pour le titre/la description, Shopify lui-même
        n'est pas modifié : c'est à l'intégration qui publie réellement
        sur la marketplace de récupérer cette URL et d'y associer son
        propre visuel."""
        self.ensure_one()
        if not self.image_override or not self.id:
            return False
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not base_url:
            _logger.warning(
                "web.base.url n'est pas configuré : impossible de générer "
                "l'URL de l'image marketplace pour "
                "shopify.product.marketplace.content %s.",
                self.id,
            )
            return False
        return (
            f"{base_url}/web/image/shopify.product.marketplace.content/"
            f"{self.id}/image_override"
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
        if self.env.context.get("shopify_sync"):
            return result

        # Seule la ligne "amazon" remplace directement le nom du produit
        # Odoo (pas de titre dupliqué, Shopify n'a qu'un seul titre par
        # produit de toute façon). Les autres marketplaces (Etsy, ...)
        # gardent le comportement d'origine : leur titre reste un
        # métachamp séparé, sans toucher au nom du produit ni aux autres
        # marketplaces.
        templates_pushed = self.env["product.template"]
        if vals.get("title_override"):
            for content in self:
                if content.marketplace_id.code != "amazon":
                    continue
                template = content.product_tmpl_id
                if template.name != vals["title_override"]:
                    template.write({"name": vals["title_override"]})
                    templates_pushed |= template

        if {"title_override", "description_override", "image_override"}.intersection(vals.keys()):
            # Renvoie aussi les métachamps marketplace (description,
            # image, titre vidé = retour au titre générique, ou toute
            # marketplace autre qu'amazon). Évite un second envoi pour les
            # produits déjà renvoyés ci-dessus (ligne amazon).
            for content in self:
                template = content.product_tmpl_id
                if template in templates_pushed:
                    continue
                template.with_context(shopify_sync=True)._shopify_push_one()
        return result

    def unlink(self):
        # On garde les produits concernés AVANT la suppression : une fois
        # la ligne supprimée, on ne pourrait plus remonter jusqu'à eux.
        templates = self.mapped("product_tmpl_id")
        sync = not self.env.context.get("shopify_sync")
        result = super().unlink()
        if sync:
            # Supprimer une ligne doit aussi supprimer le métachamp
            # correspondant côté Shopify (sinon l'ancien titre/description
            # reste affiché indéfiniment pour cette marketplace).
            for template in templates:
                template.with_context(shopify_sync=True)._shopify_push_one()
        return result
