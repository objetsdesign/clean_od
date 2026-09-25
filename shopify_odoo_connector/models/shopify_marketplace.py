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
import hashlib
import html
import json
import logging
import re
import secrets
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .etsy_api_client import (
    EtsyAPIClient,
    EtsyAPIError,
    etsy_authorize_url,
    etsy_pkce_pair,
)

_logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"[^a-z0-9_]+")

# Champs d'une ligne marketplace qui, pour une marketplace en mode
# "produit dédié" (Etsy), doivent aussi déclencher le renvoi du produit
# Shopify dédié (en plus des champs communs titre/description/prix/...).
_DEDICATED_PUSH_FIELDS = {
    "amazon_bullet_points",
    "amazon_search_terms",
    "amazon_browse_node_id",
    "amazon_product_type",
    "amazon_gtin",
    "amazon_brand",
    "amazon_condition_type",
    "amazon_country_of_origin",
    "amazon_safety_warning",
    "etsy_style_tags",
    "etsy_materials",
    "etsy_who_made",
    "etsy_when_made",
    "etsy_is_supply",
    "etsy_listing_id",
}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _shopify_html_to_text(value):
    """Convertit un texte HTML (ex : product.template.description, au
    format HTML avec balises <div>/<strong>/...) en texte brut lisible,
    pour l'envoi dans un métachamp Shopify de type texte (pas de balises
    affichées telles quelles) ou pour pré-remplir un champ texte simple."""
    if not value:
        return ""
    text = _HTML_TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _html_to_etsy_text(value):
    """HTML -> texte brut pour la description Etsy (Etsy n'accepte pas le
    HTML), en conservant les retours à la ligne des paragraphes/listes."""
    if not value:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


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

    # ------------------------------------------------------------------
    # MODE DE PUBLICATION : comment le contenu de cette marketplace
    # arrive jusqu'à l'app Shopify qui publie réellement dessus.
    # ------------------------------------------------------------------
    # Problème résolu : les apps tierces (app Amazon, OrderBridge pour
    # Etsy, ...) lisent TOUTES les champs standards du produit Shopify
    # (title / body_html / images / tags / prix). Elles ignorent les
    # métachamps "marketplace_<code>". Si Amazon ET Etsy lisent le même
    # produit Shopify, Etsy reçoit forcément la fiche Amazon.
    #  * standard  : le contenu est recopié sur la fiche Odoo, donc sur le
    #                produit Shopify principal (cas Amazon, inchangé).
    #  * dedicated : un produit Shopify SÉPARÉ est créé pour cette
    #                marketplace, avec son propre titre/description/
    #                photos/prix/tags. C'est CE produit que l'app tierce
    #                (OrderBridge) doit pousser vers Etsy.
    #  * metafield : métachamps uniquement (comportement historique).
    shopify_publish_mode = fields.Selection(
        [
            ("shopify_main", "Champs standards du produit Shopify (lus par OrderBridge)"),
            ("standard", "Fiche principale + recopie sur la fiche Odoo (ancien mode)"),
            ("etsy_api", "Annonce Etsy mise à jour directement (API Etsy)"),
            ("dedicated", "Produit Shopify dédié (2e produit Shopify)"),
            ("metafield", "Métachamps uniquement"),
        ],
        string="Mode de publication Shopify",
        compute="_compute_shopify_publish_mode",
        store=True,
        readonly=False,
        # Pas de required=True : un champ calculé stocké obligatoire est
        # inséré à NULL avant son calcul (échec à l'installation).
        help=(
            "Champs standards Shopify : le titre / la description / le prix "
            "/ les tags de CETTE fiche deviennent ceux du produit Shopify "
            "unique (ce qu'OrderBridge envoie à Etsy). La fiche Odoo n'est "
            "pas modifiée. Une seule marketplace dans ce mode.\n"
            "Métachamps : la fiche part en métachamps marketplace_<code>.* "
            "sur le même produit Shopify (ex : Amazon).\n"
            "Fiche principale (ancien mode) : le contenu remplace celui de la fiche "
            "produit standard (une seule marketplace devrait utiliser ce "
            "mode).\nAPI Etsy : UN SEUL produit Shopify ; Odoo met à jour "
            "directement l'annonce Etsy (titre, description, tags, prix) "
            "via l'API Etsy. OrderBridge ne gère plus que commandes, "
            "suivi et stock.\nProduit dédié : un produit Shopify séparé est créé "
            "pour cette marketplace, à pousser par son app (OrderBridge "
            "pour Etsy).\nMétachamps : contenu envoyé uniquement en "
            "métachamps sur le produit principal."
        ),
    )
    shopify_product_type = fields.Char(
        string="Type de produit Shopify (produit dédié)",
        compute="_compute_shopify_product_type",
        store=True,
        readonly=False,
        help=(
            "Écrit dans le champ 'Type de produit' des produits Shopify "
            "dédiés à cette marketplace. Sert à les isoler : collection "
            "automatique 'Type de produit = Etsy' à filtrer dans "
            "OrderBridge, et à EXCLURE dans l'app Amazon."
        ),
    )
    shopify_sku_suffix = fields.Char(
        string="Suffixe SKU (produit dédié)",
        compute="_compute_shopify_sku_suffix",
        store=True,
        readonly=False,
        help=(
            "Ajouté aux SKU des variantes du produit dédié (ex : -ETSY) "
            "pour qu'OrderBridge ne confonde pas le produit dédié avec le "
            "produit principal (il associe les commandes Etsy par SKU). "
            "Laisser vide si vos annonces Etsy utilisent déjà le SKU "
            "d'origine et que vous les liez manuellement dans OrderBridge."
        ),
    )
    shopify_hide_from_online_store = fields.Boolean(
        string="Masquer le produit dédié de la boutique en ligne",
        default=True,
        help=(
            "Le produit dédié est créé non publié sur le canal Boutique "
            "en ligne : vos clients Shopify ne voient pas de doublon."
        ),
    )

    # ------------------------------------------------------------------
    # CONNEXION API ETSY (mode "etsy_api")
    # ------------------------------------------------------------------
    etsy_keystring = fields.Char(
        string="Keystring Etsy",
        groups="shopify_odoo_connector.group_shopify_manager",
        help="Etsy > developers > Your apps > votre app > Keystring.",
    )
    etsy_shared_secret = fields.Char(
        string="Shared secret Etsy",
        groups="shopify_odoo_connector.group_shopify_manager",
    )
    etsy_access_token = fields.Char(groups="base.group_system", copy=False)
    etsy_refresh_token = fields.Char(groups="base.group_system", copy=False)
    etsy_token_expires_at = fields.Float(groups="base.group_system", copy=False)
    etsy_oauth_state = fields.Char(groups="base.group_system", copy=False)
    etsy_code_verifier = fields.Char(groups="base.group_system", copy=False)
    etsy_shop_id = fields.Char(string="ID boutique Etsy", copy=False)
    etsy_connected = fields.Boolean(string="Etsy connecté", copy=False, readonly=True)
    etsy_redirect_uri = fields.Char(
        string="URL de rappel (à déclarer chez Etsy)",
        compute="_compute_etsy_redirect_uri",
    )
    etsy_sync_price = fields.Boolean(
        string="Envoyer le prix Etsy",
        default=True,
        help="Met à jour le prix de l'annonce Etsy avec le prix de la ligne "
        "Etsy (converti avec le taux ci-dessous). Les quantités Etsy ne "
        "sont jamais modifiées par Odoo (gérées par OrderBridge).",
    )
    etsy_price_rate = fields.Float(
        string="Taux de conversion prix Odoo → devise Etsy",
        default=1.0,
        digits=(12, 6),
        help="Prix Etsy = prix Odoo × ce taux. Ex. boutique Etsy en EUR et "
        "prix Odoo en DT : mettre le taux DT→EUR. 1 = même devise.",
    )

    def _compute_etsy_redirect_uri(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        for marketplace in self:
            marketplace.etsy_redirect_uri = f"{base_url.rstrip('/')}/shopify/etsy/oauth/callback"

    def _etsy_store_token(self, token):
        self.ensure_one()
        self.sudo().write(
            {
                "etsy_access_token": token.get("access_token"),
                "etsy_refresh_token": token.get("refresh_token") or self.sudo().etsy_refresh_token,
                "etsy_token_expires_at": time.time() + int(token.get("expires_in") or 3600),
            }
        )

    def _etsy_client(self):
        self.ensure_one()
        return EtsyAPIClient(self.sudo())

    def action_etsy_connect(self):
        """Bouton « Connecter Etsy » : lance l'autorisation OAuth (PKCE)."""
        self.ensure_one()
        acc = self.sudo()
        if not acc.etsy_keystring or not acc.etsy_shared_secret:
            raise UserError(_("Renseignez d'abord le Keystring et le Shared secret Etsy."))
        verifier, challenge = etsy_pkce_pair()
        state = secrets.token_urlsafe(24)
        acc.write({"etsy_oauth_state": state, "etsy_code_verifier": verifier})
        return {
            "type": "ir.actions.act_url",
            "url": etsy_authorize_url(acc.etsy_keystring, self.etsy_redirect_uri, state, challenge),
            "target": "self",
        }

    def action_etsy_disconnect(self):
        self.sudo().write(
            {
                "etsy_access_token": False,
                "etsy_refresh_token": False,
                "etsy_token_expires_at": 0,
                "etsy_connected": False,
            }
        )
        return True

    def action_etsy_test(self):
        """Bouton « Tester la connexion » : lit le vendeur et sa boutique."""
        self.ensure_one()
        try:
            me = self._etsy_client().get_me()
        except EtsyAPIError as exc:
            raise UserError(_("Connexion Etsy impossible :\n%s") % exc) from exc
        if me.get("shop_id"):
            self.sudo().write({"etsy_shop_id": str(me["shop_id"]), "etsy_connected": True})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Etsy"),
                "message": _("Connexion OK — boutique Etsy n° %s") % (me.get("shop_id") or "?"),
                "type": "success",
            },
        }

    @api.depends("platform_type")
    def _compute_shopify_publish_mode(self):
        # Valeur proposée selon le type (Amazon -> fiche principale,
        # Etsy -> produit dédié), librement modifiable ensuite.
        defaults = {"amazon": "metafield", "etsy": "shopify_main"}
        for marketplace in self:
            marketplace.shopify_publish_mode = defaults.get(
                marketplace.platform_type, "metafield"
            )

    @api.depends("name")
    def _compute_shopify_product_type(self):
        for marketplace in self:
            if not marketplace.shopify_product_type:
                marketplace.shopify_product_type = marketplace.name or False

    @api.depends("platform_type")
    def _compute_shopify_sku_suffix(self):
        for marketplace in self:
            if not marketplace.shopify_sku_suffix and marketplace.platform_type == "etsy":
                marketplace.shopify_sku_suffix = "-ETSY"

    @api.onchange("shopify_publish_mode")
    def _onchange_shopify_publish_mode(self):
        # Deux marketplaces en mode "fiche principale" écraseraient la
        # fiche Odoo l'une après l'autre : c'est exactement le problème
        # Amazon/Etsy qu'on veut éviter. Simple avertissement (pas de
        # blocage : ex. Amazon FR + Amazon DE partageant le même texte).
        if self.shopify_publish_mode not in ("standard", "shopify_main"):
            return
        others = self.search(
            [
                ("shopify_publish_mode", "in", ("standard", "shopify_main")),
                ("active", "=", True),
                ("id", "!=", self._origin.id or 0),
            ]
        )
        if others:
            return {
                "warning": {
                    "title": _("Plusieurs marketplaces sur la fiche principale"),
                    "message": _(
                        "%s utilise déjà la fiche Shopify principale. Deux "
                        "marketplaces dans ce mode partagent (et écrasent) "
                        "le même contenu. Pour un contenu distinct, "
                        "choisissez « Produit Shopify dédié »."
                    )
                    % ", ".join(others.mapped("name")),
                }
            }

    def action_shopify_push_products(self):
        """Bouton : renvoie vers Shopify tous les produits ayant une ligne
        pour cette marketplace (à utiliser après un changement de mode :
        création / suppression des produits dédiés)."""
        contents = self.env["shopify.product.marketplace.content"].search(
            [("marketplace_id", "in", self.ids)]
        )
        for template in contents.product_tmpl_id:
            template._shopify_push_one()
        return True

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

    _DEFAULT_MARKETPLACES = [
        {"name": "Amazon", "code": "amazon", "platform_type": "amazon", "sequence": 10,
         "shopify_publish_mode": "metafield"},
        {"name": "Etsy", "code": "etsy", "platform_type": "etsy", "sequence": 20,
         "shopify_publish_mode": "shopify_main"},
        {"name": "TikTok Shop", "code": "tiktok", "platform_type": "tiktok", "sequence": 30,
         "shopify_publish_mode": "metafield"},
    ]

    def _shopify_migrate_etsy_api_mode(self):
        """Une seule fois (v4.2) : Etsy passe du mode "produit dédié" au
        mode "API Etsy" (un seul produit Shopify), et les produits Shopify
        dédiés Etsy déjà créés sont supprimés de Shopify."""
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.etsy_api_mode_migrated"
        if param.get_param(key):
            return
        etsy = self.sudo().with_context(active_test=False).search(
            [("platform_type", "=", "etsy"), ("shopify_publish_mode", "=", "dedicated")]
        )
        if etsy:
            etsy.write({"shopify_publish_mode": "etsy_api"})
            links = self.env["shopify.marketplace.product.link"].sudo().search(
                [("marketplace_id", "in", etsy.ids)]
            )
            for template in links.product_tmpl_id:
                try:
                    template._shopify_cleanup_marketplace_dedicated_products()
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "Suppression du produit Shopify dédié Etsy impossible pour %s",
                        template.display_name,
                    )
        param.set_param(key, "1")

    def _shopify_migrate_two_fiches_one_product(self):
        """Une seule fois (v4.3) : 1 produit Odoo (2 fiches) -> 1 produit
        Shopify. Etsy -> champs standards Shopify (lus par OrderBridge),
        Amazon -> métachamps. Supprime les éventuels produits Shopify
        dédiés restants."""
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.two_fiches_one_product_migrated"
        if param.get_param(key):
            return
        records = self.sudo().with_context(active_test=False)
        records.search([("platform_type", "=", "etsy")]).write({"shopify_publish_mode": "shopify_main"})
        records.search([("platform_type", "=", "amazon")]).write({"shopify_publish_mode": "metafield"})
        links = self.env["shopify.marketplace.product.link"].sudo().search([])
        for template in links.product_tmpl_id:
            try:
                template._shopify_cleanup_marketplace_dedicated_products()
            except Exception:  # noqa: BLE001
                _logger.exception("Suppression produit Shopify dédié impossible : %s", template.display_name)
        param.set_param(key, "1")

    def _shopify_ensure_default_marketplaces(self):
        """Garantit l'existence d'Amazon / Etsy / TikTok Shop (get-or-create
        par code), sans jamais tenter de les recréer si une ligne avec ce
        code existe déjà (créée manuellement par un utilisateur ou par une
        version antérieure du module) : on se contente alors de compléter
        son `platform_type` s'il est resté à 'generic'. Rejoué à chaque
        install/upgrade via un <function>, donc idempotent et sans risque
        de doublon (voir data/shopify_marketplace_data.xml)."""
        existing = {m.code: m for m in self.sudo().with_context(active_test=False).search([])}
        for vals in self._DEFAULT_MARKETPLACES:
            record = existing.get(vals["code"])
            if not record:
                self.sudo().create(vals)
            elif record.platform_type == "generic":
                record.sudo().write({"platform_type": vals["platform_type"]})


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
    marketplace_publish_mode = fields.Selection(
        related="marketplace_id.shopify_publish_mode",
        string="Mode de publication",
        readonly=True,
    )
    company_currency_id = fields.Many2one(
        related="product_tmpl_id.currency_id", string="Devise", readonly=True
    )
    product_gallery_image_ids = fields.One2many(
        "product.image",
        "product_tmpl_id",
        related="product_tmpl_id.product_template_image_ids",
        string="Galerie produit (référence)",
        readonly=True,
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
        string="Prix spécifique",
        digits="Product Price",
        help="Prix affiché sur CETTE marketplace. Laissez vide (0) pour utiliser automatiquement le prix de vente du produit (voir 'Prix envoyé' ci-contre).",
    )
    stock_override = fields.Integer(
        string="Stock affiché",
        help=(
            "Quantité à afficher sur CETTE marketplace si elle doit "
            "différer du stock Odoo réel (ex : quota volontairement "
            "limité sur une marketplace). Laissez vide pour suivre le "
            "stock Odoo (voir 'Stock envoyé' ci-contre)."
        ),
    )
    # ------------------------------------------------------------------
    # Champs de lecture seule (non stockés) : montrent la valeur QUI SERA
    # RÉELLEMENT ENVOYÉE à Shopify pour cette marketplace, en direct à
    # partir de la fiche produit. Utile pour ne pas laisser croire que
    # "Prix spécifique" à 0,00 signifie "prix nul envoyé" : par défaut
    # (champ vide), c'est ce prix produit qui part, et il se met à jour
    # tout seul si le prix du produit change (aucune action requise ici).
    # ------------------------------------------------------------------
    effective_title = fields.Char(
        string="Titre envoyé",
        compute="_compute_effective_fields",
        help="Titre réellement envoyé à Shopify pour cette marketplace : la surcharge ci-dessus si renseignée, sinon le nom du produit.",
    )
    effective_price = fields.Float(
        string="Prix envoyé",
        digits="Product Price",
        compute="_compute_effective_fields",
        help="Prix réellement envoyé à Shopify pour cette marketplace : le prix spécifique ci-dessus si renseigné, sinon le prix de vente actuel du produit.",
    )
    effective_stock = fields.Integer(
        string="Stock envoyé",
        compute="_compute_effective_fields",
        help="Stock réellement suivi pour cette marketplace : le stock spécifique ci-dessus si renseigné, sinon le stock Odoo actuel.",
    )
    effective_description = fields.Html(
        string="Description envoyée",
        sanitize=False,
        compute="_compute_effective_fields",
        help="Description réellement envoyée à Shopify pour cette marketplace : la surcharge ci-dessus si renseignée, sinon la description du produit. Lecture seule : affichage HTML rendu, la description du produit étant elle-même au format HTML.",
    )
    effective_image = fields.Image(
        string="Image envoyée",
        compute="_compute_effective_fields",
        help="Image réellement envoyée à Shopify pour cette marketplace : l'image spécifique ci-dessus si renseignée, sinon l'image principale du produit.",
    )

    AMAZON_TITLE_MAX_LEN = 75

    @api.constrains("title_override", "marketplace_id")
    def _check_amazon_title_length(self):
        """Amazon limite le titre produit à 75 caractères (espaces
        compris), catégories Media (Livres, Musique, DVD, Vidéo...)
        exclues. Porte sur le titre Amazon RÉELLEMENT envoyé
        (`effective_title` de cette ligne, donc `title_override` si
        renseigné sinon le nom du produit) : depuis que chaque
        marketplace a son propre produit Shopify dédié, ce titre n'est
        plus forcément identique au nom du produit Odoo."""
        for content in self:
            if content.marketplace_id.platform_type != "amazon":
                continue
            product = content.product_tmpl_id
            if "media" in (product.categ_id.complete_name or "").lower():
                continue
            title = content.effective_title or ""
            if len(title) > self.AMAZON_TITLE_MAX_LEN:
                raise ValidationError(
                    _(
                        "Le titre Amazon \"%(name)s\" dépasse %(max)s caractères "
                        "(%(actual)s caractères, espaces compris), la limite "
                        "imposée par Amazon. Cette limite ne s'applique pas aux "
                        "catégories Media (Livres, Musique, DVD, Vidéo...)."
                    )
                    % {
                        "name": title,
                        "max": self.AMAZON_TITLE_MAX_LEN,
                        "actual": len(title),
                    }
                )

    @api.depends(
        "title_override",
        "price_override",
        "stock_override",
        "description_override",
        "image_override",
        "product_tmpl_id.name",
        "product_tmpl_id.list_price",
        "product_tmpl_id.description",
        "product_tmpl_id.qty_available",
        "product_tmpl_id.image_1920",
    )
    def _compute_effective_fields(self):
        for content in self:
            product = content.product_tmpl_id
            content.effective_title = content.title_override or product.name
            content.effective_price = content.price_override or product.list_price
            content.effective_stock = (
                content.stock_override if content.stock_override else product.qty_available
            )
            content.effective_description = content.description_override or product.description or ""
            content.effective_image = content.image_override or product.image_1920

    variant_ids = fields.One2many(
        "shopify.product.marketplace.variant",
        "content_id",
        string="Variantes",
        help="Titre/SKU/prix/stock propres à chaque variante, pour CETTE marketplace.",
    )

    shopify_marketplace_push_status = fields.Text(
        string="Statut d'envoi Shopify",
        compute="_compute_shopify_marketplace_push_status",
        help=(
            "Produit Shopify DÉDIÉ à cette marketplace (distinct du "
            "produit Shopify par défaut de la boutique), un par boutique "
            "liée à ce produit."
        ),
    )

    @api.depends(
        "product_tmpl_id.shopify_link_ids.config_id",
        "marketplace_id",
        "marketplace_id.shopify_publish_mode",
    )
    def _compute_shopify_marketplace_push_status(self):
        Link = self.env["shopify.marketplace.product.link"].sudo()
        for content in self:
            if content.marketplace_id.shopify_publish_mode != "dedicated":
                content.shopify_marketplace_push_status = (
                    "Pas de produit Shopify dédié pour cette marketplace "
                    "(mode : fiche principale ou métachamps)."
                )
                continue
            configs = content.product_tmpl_id.shopify_link_ids.config_id
            if not configs:
                content.shopify_marketplace_push_status = (
                    "Produit non encore lié à une boutique Shopify."
                )
                continue
            lines = []
            for config in configs:
                link = Link.search(
                    [
                        ("config_id", "=", config.id),
                        ("product_tmpl_id", "=", content.product_tmpl_id.id),
                        ("marketplace_id", "=", content.marketplace_id.id),
                    ],
                    limit=1,
                )
                if link and link.shopify_product_id:
                    lines.append(
                        f"{config.display_name} : produit Shopify #{link.shopify_product_id}"
                        f" (dernière synchro {link.last_sync or '—'})"
                    )
                else:
                    lines.append(f"{config.display_name} : pas encore envoyé")
            content.shopify_marketplace_push_status = "\n".join(lines)

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
    etsy_listing_id = fields.Char(
        string="N° annonce Etsy",
        copy=False,
        help="Rempli automatiquement depuis le métachamp "
        "orderbridge/etsy_listing_id que OrderBridge écrit sur le produit "
        "Shopify. Peut aussi être saisi à la main (nombre dans l'URL "
        "etsy.com/listing/<numéro>/...).",
    )
    etsy_push_status = fields.Text(string="Dernier envoi Etsy", readonly=True, copy=False)
    shopify_fiche_gid = fields.Char(
        string="ID fiche Shopify (métaobjet)", copy=False, readonly=True,
        help="Fiche « Fiche marketplace » correspondante dans Shopify, "
        "sélectionnable dans le champ « Fiche active » du produit Shopify.",
    )
    etsy_last_push_hash = fields.Char(copy=False)

    # ------------------------------------------------------------------
    # ENVOI DIRECT VERS L'ANNONCE ETSY (mode "etsy_api")
    # ------------------------------------------------------------------
    def _etsy_split(self, value, max_items=13, max_len=None):
        items = [v.strip() for v in (value or "").split(",") if v.strip()]
        if max_len:
            items = [v[:max_len] for v in items]
        return items[:max_items]

    def _etsy_listing_fields(self):
        """Champs updateListing envoyés à Etsy, pris sur CETTE ligne Etsy
        (jamais sur la fiche Odoo standard, qui porte le contenu Amazon)."""
        self.ensure_one()
        vals = {"title": (self.effective_title or "")[:140]}
        description = _html_to_etsy_text(self.description_override) or _html_to_etsy_text(
            self.product_tmpl_id.description
        )
        if description:
            vals["description"] = description
        tags = self._etsy_split(self.etsy_style_tags, max_len=20)
        if tags:
            vals["tags"] = tags
        materials = self._etsy_split(self.etsy_materials)
        if materials:
            vals["materials"] = materials
        if self.etsy_who_made:
            vals["who_made"] = self.etsy_who_made
        if self.etsy_when_made:
            vals["when_made"] = self.etsy_when_made
        vals["is_supply"] = bool(self.etsy_is_supply)
        # Poids de l'article : exigé par l'éditeur Etsy pour un article
        # physique. Une annonce créée/mise à jour par API sans poids ne peut
        # plus être enregistrée à la main dans Etsy (erreur « Poids de
        # l'article »).
        weight, unit = self.product_tmpl_id._shopify_weight_and_unit()
        if weight:
            vals["item_weight"] = weight
            vals["item_weight_unit"] = unit
        return vals

    def _etsy_price_for_sku(self, sku, single_product):
        """Prix Odoo (devise Odoo) à appliquer à un produit de
        l'inventaire Etsy : variante reconnue par SKU (SKU Odoo ou SKU de
        la ligne variante Etsy), sinon prix de la ligne si l'annonce n'a
        qu'un seul produit ; None = on ne touche pas au prix."""
        self.ensure_one()
        base_price = self._shopify_marketplace_effective_price()
        template_price = self.product_tmpl_id.list_price
        sku = (sku or "").strip()
        if sku:
            for line in self.variant_ids:
                if sku in {(line.sku_override or "").strip(), (line.product_id.default_code or "").strip()}:
                    variant = line.product_id
                    # Prix variante personnalisé sur la ligne Etsy (différent
                    # du prix standard de la variante) : prioritaire.
                    if line.price_override and abs(line.price_override - variant.lst_price) > 0.001:
                        return line.price_override
                    # Sinon : prix Etsy de la ligne + supplément de la variante.
                    return base_price + (variant.lst_price - template_price)
            variant = self.product_tmpl_id.product_variant_ids.filtered(
                lambda v: (v.default_code or "").strip() == sku
            )[:1]
            if variant:
                return base_price + (variant.lst_price - template_price)
        if single_product:
            return base_price
        return None

    @staticmethod
    def _etsy_clean_inventory(inventory):
        """Transforme la réponse getListingInventory en corps valide pour
        updateListingInventory (champs en lecture seule retirés, prix
        {amount, divisor} convertis en décimal) — conformément à la doc
        Etsy. Les quantités sont conservées telles quelles."""
        products = []
        for product in inventory.get("products") or []:
            offerings = []
            for offering in product.get("offerings") or []:
                price = offering.get("price")
                if isinstance(price, dict):
                    divisor = price.get("divisor") or 100
                    price = round((price.get("amount") or 0) / divisor, 2)
                clean = {
                    "price": price,
                    "quantity": offering.get("quantity", 0),
                    "is_enabled": offering.get("is_enabled", True),
                }
                if offering.get("readiness_state_id"):
                    clean["readiness_state_id"] = offering["readiness_state_id"]
                offerings.append(clean)
            property_values = []
            for prop in product.get("property_values") or []:
                prop = dict(prop)
                prop.pop("scale_name", None)
                property_values.append(prop)
            products.append(
                {
                    "sku": product.get("sku") or "",
                    "offerings": offerings,
                    "property_values": property_values,
                }
            )
        body = {"products": products}
        for key in (
            "price_on_property",
            "quantity_on_property",
            "sku_on_property",
            "readiness_state_on_property",
        ):
            if key in inventory:
                body[key] = inventory.get(key) or []
        return body

    def _etsy_push_price(self, client, account, listing_id):
        self.ensure_one()
        inventory = client.get_listing_inventory(listing_id)
        body = self._etsy_clean_inventory(inventory)
        single = len(body["products"]) == 1
        rate = account.etsy_price_rate or 1.0
        changed = False
        for product in body["products"]:
            odoo_price = self._etsy_price_for_sku(product.get("sku"), single)
            if odoo_price is None:
                continue
            new_price = round(odoo_price * rate, 2)
            for offering in product["offerings"]:
                if offering.get("price") != new_price:
                    offering["price"] = new_price
                    changed = True
        if changed:
            client.update_listing_inventory(listing_id, body)
        return changed

    def _etsy_log(self, config, listing_id, state, message):
        self.ensure_one()
        config = config or self.product_tmpl_id.shopify_link_ids.config_id[:1]
        if not config:
            return
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "out",
                "model_name": "product.template",
                "res_id": self.product_tmpl_id.id,
                "shopify_object_type": "etsy listing",
                "shopify_object_id": str(listing_id or ""),
                "state": state,
                "message": message,
            }
        )

    def _etsy_api_push(self, listing_id=None, force=False, config=None):
        """Met à jour l'annonce Etsy de CETTE ligne. Ne fait rien si le
        contenu n'a pas changé depuis le dernier envoi (sauf `force`)."""
        self.ensure_one()
        account = self.marketplace_id.sudo()
        listing_id = listing_id or self.etsy_listing_id
        now = fields.Datetime.now()
        if not listing_id:
            self.with_context(shopify_sync=True).write(
                {
                    "etsy_push_status": _(
                        "%s : annonce Etsy pas encore liée. Poussez ce produit une "
                        "première fois dans OrderBridge (Product Push > Create New "
                        "Draft) ou saisissez le n° d'annonce Etsy."
                    )
                    % now
                }
            )
            return False
        if not account.etsy_refresh_token or not account.etsy_shop_id:
            self.with_context(shopify_sync=True).write(
                {"etsy_push_status": _("%s : Etsy non connecté (fiche marketplace Etsy).") % now}
            )
            return False
        listing_fields = self._etsy_listing_fields()
        price_part = (
            [self._shopify_marketplace_effective_price()] + self.variant_ids.mapped("effective_price")
            if account.etsy_sync_price
            else []
        )
        digest = hashlib.md5(
            json.dumps(
                [listing_id, listing_fields, price_part, account.etsy_price_rate],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if not force and digest == self.etsy_last_push_hash:
            return True
        client = account._etsy_client()
        try:
            client.update_listing(account.etsy_shop_id, listing_id, listing_fields)
            price_msg = ""
            if account.etsy_sync_price:
                price_msg = _(" + prix") if self._etsy_push_price(client, account, listing_id) else ""
            self.with_context(shopify_sync=True).write(
                {
                    "etsy_listing_id": str(listing_id),
                    "etsy_last_push_hash": digest,
                    "etsy_push_status": _("%(date)s : annonce Etsy %(id)s mise à jour (titre, description, tags%(price)s).")
                    % {"date": now, "id": listing_id, "price": price_msg},
                }
            )
            self._etsy_log(config, listing_id, "success", _("Annonce Etsy mise à jour depuis Odoo."))
            return True
        except EtsyAPIError as exc:
            _logger.warning("Échec mise à jour annonce Etsy %s : %s", listing_id, exc)
            self.with_context(shopify_sync=True).write(
                {"etsy_push_status": _("%(date)s : ERREUR Etsy — %(err)s") % {"date": now, "err": exc}}
            )
            self._etsy_log(config, listing_id, "error", str(exc))
            return False

    def _shopify_platform_metafield_specs(self, namespace):
        """Métachamps SUPPLÉMENTAIRES propres au type de marketplace (ex :
        bloc Amazon : points clés, marque, GTIN...), pour que l'app de la
        marketplace puisse les mapper (fiche Amazon complète dans le
        produit Shopify unique)."""
        self.ensure_one()
        specs = []
        text, line = "multi_line_text_field", "single_line_text_field"
        if self.marketplace_platform_type == "amazon":
            for key, value, mtype in (
                ("bullet_points", self.amazon_bullet_points, text),
                ("search_terms", self.amazon_search_terms, line),
                ("browse_node_id", self.amazon_browse_node_id, line),
                ("product_type", self.amazon_product_type, line),
                ("gtin", self.amazon_gtin, line),
                ("brand", self.amazon_brand or self.product_tmpl_id.shopify_vendor, line),
                ("condition_type", self.amazon_condition_type, line),
                ("country_of_origin", self.amazon_country_of_origin, line),
                ("safety_warning", self.amazon_safety_warning, text),
            ):
                if value:
                    specs.append((namespace, key, str(value), mtype))
        elif self.marketplace_platform_type == "etsy":
            for key, value, mtype in (
                ("tags", self.etsy_style_tags, line),
                ("materials", self.etsy_materials, line),
                ("who_made", self.etsy_who_made, line),
                ("when_made", self.etsy_when_made, line),
            ):
                if value:
                    specs.append((namespace, key, str(value), mtype))
        return specs

    def _shopify_main_variant_sku(self, variant):
        """SKU de la variante dans CETTE fiche (onglet Variantes de la
        ligne), sinon SKU Odoo."""
        self.ensure_one()
        line = self.variant_ids.filtered(lambda l: l.product_id == variant)[:1]
        return (line.sku_override or "").strip() or variant.default_code or ""

    def _shopify_main_variant_price(self, variant):
        """Prix envoyé à Shopify pour `variant` quand CETTE fiche occupe
        les champs standards : prix variante personnalisé sur la fiche,
        sinon prix de la fiche + supplément de la variante."""
        self.ensure_one()
        base_price = self._shopify_marketplace_effective_price()
        line = self.variant_ids.filtered(lambda l: l.product_id == variant)[:1]
        if line and line.price_override and abs(line.price_override - variant.lst_price) > 0.001:
            return line.price_override
        return base_price + (variant.lst_price - self.product_tmpl_id.list_price)

    def action_etsy_push_now(self):
        """Bouton de la ligne Etsy : envoi immédiat (forcé)."""
        for content in self:
            content.product_tmpl_id._shopify_push_etsy_listings(force=True)
        return True

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

    def _shopify_marketplace_effective_price(self):
        """Prix à envoyer pour CETTE marketplace : le prix spécifique
        (`price_override`) s'il est renseigné, sinon automatiquement le
        prix de vente global du produit Odoo (`list_price`). Comme pour
        le titre : rien à ressaisir tant qu'aucun prix particulier n'est
        nécessaire pour cette marketplace, et toute modification du prix
        global du produit est reprise ici sans action manuelle (le
        renvoi vers Shopify est déjà déclenché automatiquement par
        `product.template.write()` sur changement de `list_price`).
        Identique au champ calculé `effective_price` (affiché en lecture
        seule dans le popup) : centralisé ici pour l'export."""
        self.ensure_one()
        return self.price_override or self.product_tmpl_id.list_price

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

    def _shopify_marketplace_apply_changes(self, changed_fields):
        """1 produit Odoo = 1 produit Shopify, TOUJOURS — aucune
        marketplace ne crée de produit Shopify séparé. La différenciation
        Amazon/Etsy se fait uniquement via métachamps (voir
        product.template._shopify_push_marketplace_metafields), écrits
        sur le produit par défaut à chaque renvoi. En plus, AMAZON
        UNIQUEMENT recopie son contenu sur la fiche Odoo standard elle-
        même (name/description/image_1920/list_price), comme demandé
        spécifiquement pour cette marketplace. Factorisé pour être
        appelé aussi bien depuis write() que depuis create()."""
        fields_map = {
            "title_override": "name",
            "description_override": "description",
            "image_override": "image_1920",
            "price_override": "list_price",
        }
        changed_fields = set(changed_fields)
        matched = changed_fields & set(fields_map.keys())
        push_fields = changed_fields & {
            "title_override",
            "description_override",
            "image_override",
            "category_override",
            "price_override",
            "stock_override",
        }
        for content in self:
            template = content.product_tmpl_id
            # Marketplace en mode "fiche principale" (Amazon) UNIQUEMENT :
            # recopie vers la fiche produit standard (déclenche déjà le
            # renvoi complet, métachamps et produits dédiés compris).
            # Etsy (mode "produit dédié") ne touche JAMAIS la fiche
            # standard : c'est ce qui sépare le contenu Amazon du contenu
            # Etsy.
            is_standard = content.marketplace_id.shopify_publish_mode == "standard"
            if matched and is_standard:
                prod_vals = {fields_map[src]: content[src] for src in matched}
                template.write(prod_vals)
            elif push_fields or changed_fields & _DEDICATED_PUSH_FIELDS:
                # Toute autre marketplace : pas de recopie sur la fiche
                # standard, mais on renvoie le produit (métachamps + produit
                # Shopify dédié pour le mode "dedicated").
                template.with_context(shopify_sync=True)._shopify_push_one()

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("shopify_sync"):
            self._shopify_marketplace_apply_changes(vals.keys())
        return result

    def unlink(self):
        # On garde les infos nécessaires AVANT la suppression : une fois
        # la ligne supprimée, on ne pourrait plus remonter jusqu'au couple
        # (produit, marketplace) pour archiver le bon produit Shopify.
        to_archive = [(content.product_tmpl_id, content.marketplace_id) for content in self]
        templates = self.mapped("product_tmpl_id")
        sync = not self.env.context.get("shopify_sync")
        result = super().unlink()
        if sync:
            MPLink = self.env["shopify.marketplace.product.link"].sudo()
            for template, marketplace in to_archive:
                links = MPLink.search(
                    [
                        ("product_tmpl_id", "=", template.id),
                        ("marketplace_id", "=", marketplace.id),
                    ]
                )
                for link in links:
                    if link.shopify_product_id:
                        try:
                            link.config_id.get_client().rest_put(
                                f"/products/{link.shopify_product_id}.json",
                                {"product": {"id": int(link.shopify_product_id), "status": "archived"}},
                            )
                        except Exception:  # noqa: BLE001
                            _logger.exception(
                                "Erreur archivage Shopify du produit marketplace %s (%s) "
                                "suite à la suppression de la ligne marketplace.",
                                template.display_name,
                                marketplace.display_name,
                            )
                links.unlink()
                self.env["shopify.marketplace.variant.link"].sudo().search(
                    [
                        ("marketplace_id", "=", marketplace.id),
                        ("product_id", "in", template.product_variant_ids.ids),
                    ]
                ).unlink()
            # Supprimer une ligne doit aussi supprimer le métachamp
            # correspondant côté Shopify (compatibilité, voir plus haut).
            for template in templates:
                template.with_context(shopify_sync=True)._shopify_push_one()
        return result

    # ------------------------------------------------------------------
    # Auto-remplissage : "Amazon prend tous les détails du produit qui
    # existe en standard". Une nouvelle ligne marketplace est directement
    # pré-remplie (titre, description, prix, stock, image, galerie,
    # variantes) avec les données ACTUELLES du produit : un seul champ à
    # l'écran par donnée, déjà rempli, modifiable directement - pas de
    # champ vide + doublon "en lecture seule" à côté. Les lignes créées
    # AVANT l'ajout de cette fonctionnalité sont rattrapées une fois pour
    # toutes par `_shopify_marketplace_backfill_existing` (voir
    # data/shopify_marketplace_data.xml, rejoué à chaque mise à jour du
    # module, sans effet sur les lignes déjà remplies).
    # ------------------------------------------------------------------
    def _shopify_marketplace_default_vals_from_product(self, product):
        """Valeurs de pré-remplissage (titre/description/prix/stock/
        image) à partir des données ACTUELLES de `product`."""
        vals = {"title_override": product.name, "price_override": product.list_price}
        if product.description:
            vals["description_override"] = product.description
        vals["stock_override"] = int(product.qty_available)
        if product.image_1920:
            vals["image_override"] = product.image_1920
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            product = self.env["product.template"].browse(vals.get("product_tmpl_id"))
            if not product:
                continue
            for key, value in self._shopify_marketplace_default_vals_from_product(product).items():
                vals.setdefault(key, value)
        records = super().create(vals_list)
        records._shopify_marketplace_sync_variants()
        records._shopify_marketplace_sync_media()
        # Une ligne créée avec un titre/une image/un prix déjà remplis
        # (auto-rempli ci-dessus, ou saisi directement par l'utilisateur
        # à la création) doit déclencher la même recopie + le même envoi
        # que si elle avait été créée vide puis modifiée (voir write()) —
        # sinon rien ne part pour un nouveau produit.
        if not self.env.context.get("shopify_sync"):
            for record, vals in zip(records, vals_list):
                record._shopify_marketplace_apply_changes(vals.keys())
        return records

    def _shopify_marketplace_backfill_existing(self):
        """Rattrape les lignes créées AVANT l'auto-remplissage : ne
        touche QUE les champs actuellement vides (titre, description,
        prix, stock, image), pour ne jamais écraser une personnalisation
        déjà saisie manuellement entre-temps. Sans effet la deuxième
        fois (idempotent : plus rien n'est vide après le premier
        passage)."""
        for content in self.search([]):
            product = content.product_tmpl_id
            if not product:
                continue
            defaults = self._shopify_marketplace_default_vals_from_product(product)
            vals = {
                key: value
                for key, value in defaults.items()
                if not content[key]
            }
            if vals:
                content.write(vals)
            content._shopify_marketplace_sync_variants()
            content._shopify_marketplace_sync_media()

    def _shopify_marketplace_sync_variants(self):
        """Ajoute une ligne `shopify.product.marketplace.variant` pour
        chaque variante du produit qui n'en a pas encore (aucune
        suppression, aucune modification des lignes déjà présentes :
        sans risque d'écraser une personnalisation existante), déjà
        pré-remplie avec les données actuelles de la variante."""
        MarketplaceVariant = self.env["shopify.product.marketplace.variant"]
        for content in self:
            existing_variant_ids = set(content.variant_ids.product_id.ids)
            missing = content.product_tmpl_id.product_variant_ids.filtered(
                lambda v, existing=existing_variant_ids: v.id not in existing
            )
            for variant in missing:
                MarketplaceVariant.create(
                    {
                        "content_id": content.id,
                        "product_id": variant.id,
                        "title_override": variant.display_name,
                        "sku_override": variant.default_code or "",
                        "price_override": variant.lst_price,
                        "stock_override": int(variant.qty_available),
                    }
                )

    def _shopify_marketplace_sync_media(self, force=False):
        """Remplace la galerie complémentaire par une copie des photos
        actuelles de la galerie du produit. Par défaut, ne touche à rien
        si la ligne a déjà des photos (première initialisation
        uniquement) ; avec `force=True` (resynchronisation automatique
        ou bouton "Reprendre les données du produit"), remplace
        entièrement la galerie par l'état actuel du produit."""
        MarketplaceMedia = self.env["shopify.product.marketplace.media"]
        for content in self:
            if content.media_ids:
                if not force:
                    continue
                content.media_ids.unlink()
            for index, image in enumerate(content.product_tmpl_id.product_template_image_ids, start=1):
                if not image.image_1920:
                    continue
                MarketplaceMedia.create(
                    {
                        "content_id": content.id,
                        "sequence": index * 10,
                        "name": image.name,
                        "image": image.image_1920,
                    }
                )

    def action_sync_variants(self):
        """Bouton popup : (ré)ajoute les variantes manquantes."""
        self._shopify_marketplace_sync_variants()
        return True

    def action_reset_to_product(self):
        """Bouton popup "Reprendre les données du produit" : recopie le
        titre, la description, le prix, le stock, l'image principale et
        la galerie ACTUELS du produit Odoo dans cette ligne marketplace
        (écrase les valeurs actuellement saisies ici)."""
        self.ensure_one()
        product = self.product_tmpl_id
        defaults = self._shopify_marketplace_default_vals_from_product(product)
        self.write(defaults)  # déclenche déjà le renvoi du produit Shopify (voir write() ci-dessus)
        self._shopify_marketplace_sync_media(force=True)
        return True

    def action_set_as_active_fiche(self):
        """Bouton « Activer cette fiche » : rend CETTE fiche active tout de
        suite, sans attendre que l'utilisateur clique sur « Enregistrer »
        sur le formulaire produit. Le `write()` sur `product.template`
        déclenche déjà l'envoi immédiat vers Shopify (titre/prix rapide,
        puis photos/métachamps en arrière-plan) : voir
        `product.template.write()`."""
        self.ensure_one()
        if self.product_tmpl_id.shopify_active_marketplace_id == self.marketplace_id:
            return True
        self.product_tmpl_id.write({"shopify_active_marketplace_id": self.marketplace_id.id})
        return True

    def _shopify_marketplace_gallery_changed(self):
        """Une photo de galerie a changé sur cette ligne marketplace :
        renvoie le produit Shopify par défaut (1 seul produit, toujours)
        pour refléter le changement dans ses métachamps."""
        for content in self:
            template = content.product_tmpl_id
            template.with_context(shopify_sync=True)._shopify_push_one()

    def _shopify_marketplace_media_urls(self):
        """URLs des visuels à envoyer pour CETTE marketplace : la galerie
        spécifique (`media_ids`), déjà pré-remplie à la création avec les
        photos du produit (voir `_shopify_marketplace_sync_media`)."""
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not base_url:
            _logger.warning(
                "web.base.url n'est pas configuré : impossible de générer "
                "les URLs de galerie marketplace pour "
                "shopify.product.marketplace.content %s.",
                self.id,
            )
            return []
        if self.media_ids:
            return [
                f"{base_url}/web/image/shopify.product.marketplace.media/{media.id}/image"
                for media in self.media_ids
            ]
        return [
            f"{base_url}/web/image/product.image/{image.id}/image_1920"
            for image in self.product_tmpl_id.product_template_image_ids
        ]


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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.content_id._shopify_marketplace_gallery_changed()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "image" in vals or "sequence" in vals or "name" in vals:
            self.content_id._shopify_marketplace_gallery_changed()
        return result

    def unlink(self):
        contents = self.content_id
        result = super().unlink()
        contents._shopify_marketplace_gallery_changed()
        return result


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
    effective_title = fields.Char(string="Titre envoyé", compute="_compute_effective_fields")
    effective_sku = fields.Char(string="SKU envoyé", compute="_compute_effective_fields")
    effective_price = fields.Float(
        string="Prix envoyé", digits="Product Price", compute="_compute_effective_fields"
    )
    effective_stock = fields.Integer(string="Stock envoyé", compute="_compute_effective_fields")

    @api.depends(
        "title_override",
        "sku_override",
        "price_override",
        "stock_override",
        "product_id.display_name",
        "product_id.default_code",
        "product_id.lst_price",
        "product_id.qty_available",
    )
    def _compute_effective_fields(self):
        for line in self:
            product = line.product_id
            line.effective_title = line.title_override or product.display_name
            line.effective_sku = line.sku_override or product.default_code or ""
            line.effective_price = line.price_override or product.lst_price
            line.effective_stock = line.stock_override if line.stock_override else product.qty_available

    def _shopify_marketplace_variant_apply_changes(self, changed_fields):
        """Même principe que ShopifyProductMarketplaceContent._shopify_marketplace_apply_changes
        (recopie vers la variante Odoo standard AMAZON UNIQUEMENT, envoi
        vers le produit Shopify dédié pour TOUTES les marketplaces) —
        appelé depuis write() ET create()."""
        changed_fields = set(changed_fields)
        variant_fields_map = {"sku_override": "default_code", "price_override": "lst_price"}
        matched = changed_fields & set(variant_fields_map.keys())
        push_fields = changed_fields & {
            "title_override", "sku_override", "price_override", "stock_override"
        }
        for line in self:
            variant = line.product_id
            content = line.content_id
            template = content.product_tmpl_id
            is_standard = content.marketplace_id.shopify_publish_mode == "standard"
            if matched and is_standard:
                prod_vals = {}
                for src in matched:
                    dest = variant_fields_map[src]
                    new_value = line[src]
                    if variant[dest] != new_value:
                        prod_vals[dest] = new_value
                if prod_vals:
                    variant.write(prod_vals)
            elif push_fields:
                template.with_context(shopify_sync=True)._shopify_push_one()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("shopify_sync"):
            for record, vals in zip(records, vals_list):
                record._shopify_marketplace_variant_apply_changes(vals.keys())
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("shopify_sync"):
            self._shopify_marketplace_variant_apply_changes(vals.keys())
        return result

    _sql_constraints = [
        (
            "content_product_uniq",
            "unique(content_id, product_id)",
            "Cette variante a déjà une ligne pour cette marketplace.",
        ),
    ]


# ----------------------------------------------------------------------
# PRODUIT SHOPIFY DÉDIÉ PAR MARKETPLACE
# ----------------------------------------------------------------------
# À partir d'ici : chaque marketplace (Amazon, Etsy, ...) obtient son
# PROPRE produit Shopify (son propre `shopify_product_id`), distinct du
# produit Shopify "par défaut" (`shopify.product.link`, sans marketplace).
# Le titre/la description/le prix/les variantes/l'image principale sont
# poussés directement dans les champs standards (title, body_html,
# variants, images) de CE produit dédié - pas des métachamps - pour être
# lisibles par n'importe quelle app tierce (Amazon, Etsy Integration -
# DPL, ...), qui lit toujours un produit Shopify standard, jamais un
# métachamp personnalisé propre à ce connecteur.
# ----------------------------------------------------------------------
class ShopifyMarketplaceProductLink(models.Model):
    _name = "shopify.marketplace.product.link"
    _description = "Lien produit Odoo <-> produit Shopify dédié à une marketplace (par boutique)"
    _rec_name = "shopify_product_id"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    product_tmpl_id = fields.Many2one(
        "product.template", required=True, ondelete="cascade", string="Produit Odoo"
    )
    marketplace_id = fields.Many2one(
        "shopify.marketplace", required=True, ondelete="cascade", string="Marketplace"
    )
    shopify_product_id = fields.Char(
        string="ID produit Shopify (marketplace)", copy=False, index=True
    )
    shopify_handle = fields.Char(string="Handle Shopify", copy=False)
    shopify_main_image_id = fields.Char(string="ID image principale Shopify", copy=False)
    shopify_main_image_hash = fields.Char(string="Empreinte image principale", copy=False)
    shopify_gallery_hash = fields.Char(
        string="Empreinte galerie envoyée",
        copy=False,
        help="Empreinte de l'ensemble des photos envoyées : les photos ne "
        "sont renvoyées que si l'une d'elles a changé.",
    )
    last_sync = fields.Datetime(string="Dernière synchro Shopify")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "shopify_marketplace_product_uniq",
            "unique(config_id, shopify_product_id)",
            "Ce produit Shopify est déjà lié pour cette boutique/marketplace.",
        ),
        (
            "shopify_marketplace_product_tmpl_uniq",
            "unique(config_id, product_tmpl_id, marketplace_id)",
            "Ce produit Odoo a déjà un produit Shopify dédié pour cette marketplace, sur cette boutique.",
        ),
    ]


class ShopifyMarketplaceVariantLink(models.Model):
    _name = "shopify.marketplace.variant.link"
    _description = "Lien variante Odoo <-> variante Shopify dédiée à une marketplace (par boutique)"
    _rec_name = "shopify_variant_id"

    config_id = fields.Many2one(
        "shopify.config", required=True, ondelete="cascade", string="Boutique Shopify"
    )
    marketplace_id = fields.Many2one(
        "shopify.marketplace", required=True, ondelete="cascade", string="Marketplace"
    )
    product_id = fields.Many2one(
        "product.product", required=True, ondelete="cascade", string="Variante Odoo"
    )
    shopify_variant_id = fields.Char(string="ID variante Shopify (marketplace)", copy=False, index=True)
    shopify_inventory_item_id = fields.Char(
        string="ID article d'inventaire Shopify (marketplace)", copy=False, index=True
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "shopify_marketplace_variant_uniq",
            "unique(config_id, marketplace_id, shopify_variant_id)",
            "Cette variante Shopify est déjà liée pour cette boutique/marketplace.",
        ),
        (
            "shopify_marketplace_variant_product_uniq",
            "unique(config_id, marketplace_id, product_id)",
            "Cette variante Odoo est déjà liée pour cette boutique/marketplace.",
        ),
    ]
