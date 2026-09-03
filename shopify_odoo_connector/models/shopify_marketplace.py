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
    platform_type = fields.Selection(
        [
            ("amazon", "Amazon"),
            ("etsy", "Etsy"),
            ("tiktok", "TikTok Shop"),
            ("generic", "Autre / générique"),
        ],
        string="Type de marketplace",
        default="generic",
        required=True,
        help=(
            "Détermine le bloc de champs spécifiques (structure de "
            "contenu, médias attendus, informations réglementaires) "
            "affiché sur la fiche produit pour cette marketplace. "
            "'Autre / générique' n'affiche que le bloc commun."
        ),
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Ce code de marketplace est déjà utilisé."),
    ]

    @api.onchange("name")
    def _onchange_name_platform_type(self):
        # Simple confort de saisie : si l'utilisateur crée une marketplace
        # dont le nom correspond à un type connu, on pré-sélectionne le
        # bon type (il reste librement modifiable ensuite).
        guess = _slugify_code(self.name)
        if guess in ("amazon", "etsy", "tiktok"):
            self.platform_type = guess

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
    # Champ technique stocké (related) : permet d'écrire des attrs
    # `invisible="marketplace_platform_type != 'amazon'"` dans la vue
    # popup, ce qu'un accès en pointillés `marketplace_id.platform_type`
    # ne permet pas de façon fiable côté client web.
    marketplace_platform_type = fields.Selection(
        related="marketplace_id.platform_type", string="Type", store=True, readonly=True
    )
    company_currency_id = fields.Many2one(
        related="product_tmpl_id.currency_id", string="Devise", readonly=True
    )

    # ------------------------------------------------------------------
    # Bloc COMMUN : structure de base identique pour toutes les
    # marketplaces (titre, catégorie, description, médias, prix, stock,
    # variantes). Champ vide = on retombe sur la donnée générique du
    # produit Odoo.
    # ------------------------------------------------------------------
    title_override = fields.Char(
        string="Titre",
        help="Titre envoyé à CETTE marketplace. Laissez vide pour utiliser le nom du produit.",
    )
    category_override = fields.Char(
        string="Catégorie marketplace",
        help=(
            "Catégorie/rubrique propre à CETTE marketplace (ex : chemin de "
            "catégorie Amazon, taxonomie Etsy, catégorie TikTok Shop). "
            "N'a rien à voir avec la catégorie Odoo du produit : chaque "
            "marketplace a son propre référentiel de catégories."
        ),
    )
    description_override = fields.Html(
        string="Description",
        sanitize=False,
        help="Description envoyée à CETTE marketplace. Laissez vide pour utiliser la description du produit.",
    )
    image_override = fields.Binary(
        string="Image principale",
        attachment=True,
        help=(
            "Image de couverture envoyée à CETTE marketplace (upload "
            "direct, indépendant de la galerie du produit). Laissez vide "
            "pour utiliser l'image principale du produit. Utile quand une "
            "marketplace impose un visuel différent (ex : Amazon exige un "
            "fond blanc pur, Etsy accepte des mises en situation)."
        ),
    )
    image_override_filename = fields.Char(string="Nom du fichier")
    media_ids = fields.One2many(
        "shopify.product.marketplace.media",
        "content_id",
        string="Galerie médias",
        help=(
            "Photos/visuels supplémentaires spécifiques à cette "
            "marketplace, au-delà de l'image principale ci-dessus "
            "(nombre et contraintes de format variables selon la "
            "marketplace : ex. 7 max sur Amazon, mises en situation "
            "encouragées sur Etsy, format vertical recommandé sur "
            "TikTok Shop)."
        ),
    )
    price_override = fields.Float(
        string="Prix",
        digits="Product Price",
        help="Prix affiché sur CETTE marketplace. Laissez vide (0) pour utiliser le prix de vente du produit.",
    )
    stock_override = fields.Integer(
        string="Stock affiché",
        help=(
            "Quantité à afficher sur CETTE marketplace si elle doit "
            "différer du stock Odoo réel (ex : quota volontairement "
            "limité sur une marketplace). Laissez vide pour suivre le "
            "stock Odoo."
        ),
    )
    variant_ids = fields.One2many(
        "shopify.product.marketplace.variant",
        "content_id",
        string="Variantes",
        help="Titre/SKU/prix/stock propres à chaque variante, pour CETTE marketplace.",
    )

    # ------------------------------------------------------------------
    # Bloc spécifique AMAZON (structure de contenu + informations
    # réglementaires exigées par Amazon).
    # ------------------------------------------------------------------
    amazon_bullet_points = fields.Text(
        string="Points clés (bullet points)",
        help="Jusqu'à 5 points clés, un par ligne. Spécifique à la fiche Amazon.",
    )
    amazon_search_terms = fields.Char(
        string="Mots-clés de recherche (backend)",
        help="Termes de recherche Amazon (non visibles client), séparés par des virgules.",
    )
    amazon_browse_node_id = fields.Char(
        string="Browse Node ID",
        help="Identifiant de catégorie Amazon (Browse Node) correspondant à 'Catégorie marketplace'.",
    )
    amazon_product_type = fields.Char(
        string="Product Type Amazon",
        help="Valeur de taxonomie 'product_type' exigée par le flux Amazon pour cette catégorie.",
    )
    amazon_gtin = fields.Char(
        string="GTIN / EAN / UPC",
        help="Code produit normalisé exigé par Amazon (ou exemption GTIN si applicable).",
    )
    amazon_brand = fields.Char(
        string="Marque (Amazon)",
        help="Marque envoyée à Amazon. Laissez vide pour utiliser la marque du produit.",
    )
    amazon_condition_type = fields.Selection(
        [
            ("new", "Neuf"),
            ("refurbished", "Reconditionné"),
            ("used_like_new", "Occasion - comme neuf"),
            ("used_good", "Occasion - bon état"),
        ],
        string="État (Amazon)",
        default="new",
    )
    amazon_country_of_origin = fields.Char(string="Pays d'origine")
    amazon_safety_warning = fields.Text(
        string="Avertissement de sécurité",
        help="Mention réglementaire Amazon (ex : risque d'étouffement, mise en garde d'usage).",
    )

    # ------------------------------------------------------------------
    # Bloc spécifique ETSY (structure de contenu + informations
    # réglementaires/artisanales exigées par Etsy).
    # ------------------------------------------------------------------
    etsy_who_made = fields.Selection(
        [
            ("i_did", "Fait par moi"),
            ("collective", "Fait par un collectif"),
            ("someone_else", "Fait par quelqu'un d'autre"),
        ],
        string="Qui l'a fabriqué ?",
    )
    etsy_when_made = fields.Selection(
        [
            ("made_to_order", "Fabriqué à la commande"),
            ("2020_2026", "2020 - 2026"),
            ("2010_2019", "2010 - 2019"),
            ("2006_2009", "2006 - 2009"),
            ("before_2006", "Avant 2006"),
            ("vintage", "Vintage (20 ans ou plus)"),
        ],
        string="Quand a-t-il été fabriqué ?",
    )
    etsy_materials = fields.Char(
        string="Matériaux",
        help="Matériaux utilisés, séparés par des virgules (jusqu'à 13 sur Etsy).",
    )
    etsy_is_supply = fields.Boolean(
        string="C'est une fourniture (pas un produit fini)",
        help="À cocher si l'article est une fourniture/matière première plutôt qu'un objet fini.",
    )
    etsy_production_partners = fields.Text(
        string="Partenaires de production",
        help="Description des ateliers/partenaires ayant participé à la fabrication, si applicable.",
    )
    etsy_personalization_instructions = fields.Text(
        string="Instructions de personnalisation",
        help="Texte affiché à l'acheteur si l'article est personnalisable sur Etsy.",
    )
    etsy_style_tags = fields.Char(
        string="Tags de style",
        help="Mots-clés de style/recherche Etsy, séparés par des virgules (jusqu'à 13).",
    )

    # ------------------------------------------------------------------
    # Bloc spécifique TIKTOK SHOP (structure de contenu + informations
    # logistiques/réglementaires exigées par TikTok Shop).
    # ------------------------------------------------------------------
    tiktok_category_id = fields.Char(
        string="ID catégorie TikTok Shop",
        help="Identifiant de catégorie du référentiel TikTok Shop correspondant à 'Catégorie marketplace'.",
    )
    tiktok_package_weight_kg = fields.Float(string="Poids colis (kg)")
    tiktok_package_length_cm = fields.Float(string="Longueur colis (cm)")
    tiktok_package_width_cm = fields.Float(string="Largeur colis (cm)")
    tiktok_package_height_cm = fields.Float(string="Hauteur colis (cm)")
    tiktok_certifications = fields.Text(
        string="Certifications / conformité",
        help="Certificats ou documents de conformité exigés par TikTok Shop pour cette catégorie (ex : CE, normes jouets, etc.).",
    )
    tiktok_video_url = fields.Char(
        string="Vidéo produit (URL)",
        help="Lien vers la vidéo produit verticale utilisée sur la fiche TikTok Shop, si disponible.",
    )

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


class ShopifyProductMarketplaceMedia(models.Model):
    _name = "shopify.product.marketplace.media"
    _description = "Média (galerie) spécifique à une marketplace, pour un produit"
    _order = "sequence, id"
    _rec_name = "name"

    content_id = fields.Many2one(
        "shopify.product.marketplace.content",
        required=True,
        ondelete="cascade",
        string="Contenu marketplace",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Nom du fichier")
    image = fields.Binary(string="Image", required=True, attachment=True)


class ShopifyProductMarketplaceVariant(models.Model):
    _name = "shopify.product.marketplace.variant"
    _description = "Titre / SKU / prix / stock d'une variante, spécifiques à une marketplace"
    _order = "id"
    _rec_name = "product_id"

    content_id = fields.Many2one(
        "shopify.product.marketplace.content",
        required=True,
        ondelete="cascade",
        string="Contenu marketplace",
    )
    product_tmpl_id = fields.Many2one(
        related="content_id.product_tmpl_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="content_id.product_tmpl_id.currency_id", string="Devise", readonly=True
    )
    product_id = fields.Many2one(
        "product.product",
        required=True,
        ondelete="cascade",
        string="Variante",
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
    )
    title_override = fields.Char(
        string="Titre variante",
        help="Nom de la variante affiché sur cette marketplace (ex : nom d'option Amazon/Etsy). Laissez vide pour utiliser le nom Odoo de la variante.",
    )
    sku_override = fields.Char(
        string="SKU",
        help="Référence envoyée à cette marketplace pour cette variante. Laissez vide pour utiliser la référence interne Odoo.",
    )
    price_override = fields.Float(
        string="Prix",
        digits="Product Price",
        help="Prix de cette variante sur cette marketplace. Laissez vide (0) pour utiliser le prix de vente de la variante.",
    )
    stock_override = fields.Integer(
        string="Stock affiché",
        help="Quantité affichée pour cette variante sur cette marketplace. Laissez vide pour suivre le stock Odoo.",
    )

    _sql_constraints = [
        (
            "content_product_uniq",
            "unique(content_id, product_id)",
            "Cette variante a déjà une ligne pour cette marketplace.",
        ),
    ]
