# -*- coding: utf-8 -*-
import hashlib
import json
import logging

import requests
import secrets
from datetime import timedelta

import unicodedata

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .shopify_api_client import ShopifyAPIClient, ShopifyAPIError, DEFAULT_API_VERSION


def _shopify_brand_key(value):
    """Même clé que shopify_marketplace._shopify_brand_key (sans accents,
    insensible à la casse). Copiée ici pour éviter un import croisé."""
    value = unicodedata.normalize("NFKD", (value or "").strip())
    return "".join(c for c in value if not unicodedata.combining(c)).casefold()

_logger = logging.getLogger(__name__)

DEFAULT_SCOPES = (
    "read_products,write_products,"
    "read_inventory,write_inventory,"
    "read_orders,write_orders,"
    "read_customers,write_customers,"
    "read_fulfillments,write_fulfillments,"
    "read_locations,"
    "read_shipping,write_shipping,"
    # Liste "Fiches marketplace" (Fiche Amazon / Fiche Etsy) sur le produit
    "read_metaobjects,write_metaobjects,"
    "read_metaobject_definitions,write_metaobject_definitions"
)

# Topics enregistrés automatiquement après connexion OAuth
WEBHOOK_TOPICS = [
    "products/create",
    "products/update",
    "products/delete",
    "inventory_levels/update",
    "customers/create",
    "customers/update",
    "customers/delete",
    "orders/create",
    "orders/updated",
    "orders/cancelled",
    "orders/paid",
    "orders/fulfilled",
    "fulfillments/create",
    "fulfillments/update",
    "app/uninstalled",
]


class ShopifyConfig(models.Model):
    _name = "shopify.config"
    _description = "Boutique Shopify connectée"
    _inherit = ["mail.thread"]
    _rec_name = "name"

    name = fields.Char(required=True)
    shop_url = fields.Char(
        string="Domaine boutique",
        required=True,
        help="ex : monshop.myshopify.com",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)

    # --- Mode d'authentification ---
    auth_type = fields.Selection(
        [
            ("private", "Token direct (App personnalisée)"),
            ("oauth", "OAuth (App publique, multi-boutiques)"),
        ],
        default="private",
        required=True,
        string="Mode d'authentification",
        help=(
            "Token direct : recommandé pour une seule boutique. Créez une app "
            "personnalisée dans Shopify (Dev Dashboard ou admin > Apps > "
            "Develop apps), copiez le token d'accès Admin API ici.\n"
            "OAuth : nécessaire uniquement si l'app doit être installée sur "
            "plusieurs boutiques différentes par des utilisateurs tiers."
        ),
    )

    # --- Token direct (App personnalisée) ---
    access_token = fields.Char(
        string="Token d'accès Admin API",
        copy=False,
        groups="shopify_odoo_connector.group_shopify_manager",
        help="Admin API access token obtenu depuis l'onglet 'API credentials' de votre app personnalisée Shopify.",
    )

    # --- OAuth app publique (optionnel) ---
    client_id = fields.Char(string="Client ID (API key)")
    client_secret = fields.Char(
        string="Client Secret",
        help="Utilisé pour l'échange OAuth ainsi que pour vérifier la signature HMAC des webhooks entrants.",
    )
    scope = fields.Char(default=DEFAULT_SCOPES)
    oauth_state = fields.Char(copy=False)
    api_version = fields.Char(default=DEFAULT_API_VERSION)

    _AUTH_CHAR_FIELDS = ("access_token", "client_id", "client_secret")

    @staticmethod
    def _shopify_normalize_domain(value):
        """« https://MonShop.myshopify.com/admin/ » -> « monshop.myshopify.com »."""
        value = (value or "").strip().lower()
        for prefix in ("https://", "http://"):
            if value.startswith(prefix):
                value = value[len(prefix):]
        return value.split("/")[0].strip()

    @api.model
    def _shopify_find_by_domain(self, shop_domain):
        """Boutique correspondant au domaine envoyé par Shopify (en-tête
        X-Shopify-Shop-Domain), quelle que soit la façon dont le domaine a
        été saisi dans Odoo."""
        domain = self._shopify_normalize_domain(shop_domain)
        if not domain:
            return self.browse()
        config = self.search([("shop_url", "=", domain)], limit=1)
        if config:
            return config
        candidates = self.search([("shop_url", "ilike", domain)])
        return candidates.filtered(
            lambda c: self._shopify_normalize_domain(c.shop_url) == domain
        )[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sanitize_auth_vals(vals)
            if vals.get("shop_url"):
                vals["shop_url"] = self._shopify_normalize_domain(vals["shop_url"])
        configs = super().create(vals_list)
        configs._shopify_check_products_of_my_brand()
        return configs

    def write(self, vals):
        # Un copier-coller depuis l'interface Shopify (bouton "Reveal"/
        # "Afficher") ajoute très souvent un espace ou un retour à la
        # ligne invisible en fin de valeur. Un seul caractère en trop
        # dans le Client Secret suffit à faire échouer la vérification
        # HMAC OAuth ("Signature HMAC OAuth invalide") sans qu'aucune
        # erreur ne soit visible en relisant le champ. On nettoie donc
        # systématiquement ces champs avant de les stocker.
        self._sanitize_auth_vals(vals)
        if vals.get("shop_url"):
            vals["shop_url"] = self._shopify_normalize_domain(vals["shop_url"])
        result = super().write(vals)
        if {"export_brand_filter", "name", "shop_url", "active"} & set(vals):
            self._shopify_check_products_of_my_brand()
        if {"export_brand_filter", "name", "shop_url", "sync_products", "state", "active"} & set(vals):
            # Marque d'une boutique définie/modifiée (ou boutique connectée) :
            # on coche « Afficher sur Shopify » sur les produits de cette
            # marque et on les envoie tout de suite sur la boutique.
            self.env["product.template"].sudo()._shopify_migrate_recompute_display()
        return result

    @classmethod
    def _sanitize_auth_vals(cls, vals):
        for field_name in cls._AUTH_CHAR_FIELDS:
            if vals.get(field_name):
                vals[field_name] = vals[field_name].strip()

    state = fields.Selection(
        [("draft", "Brouillon"), ("connected", "Connectée"), ("error", "Erreur")],
        default="draft",
        tracking=True,
    )
    last_error = fields.Text(readonly=True)

    # --- Synchronisation ---
    sync_products = fields.Boolean(default=True)
    sync_categories = fields.Boolean(
        default=True,
        string="Synchroniser les catégories (Shopify -> Odoo)",
        help=(
            "Si activé, la catégorie standard Shopify (Product Category / "
            "taxonomy) de chaque produit importé est reportée sur la "
            "catégorie Odoo (categ_id) du produit. Import uniquement : Odoo "
            "ne renvoie jamais de catégorie vers Shopify."
        ),
    )
    sync_inventory = fields.Boolean(default=True)
    export_brand_filter = fields.Char(
        string="Marque(s) de cette boutique",
        default=False,
        help=(
            "Optionnel. Une ou plusieurs marques Odoo (champ 'Marque "
            "Shopify' / vendor), séparées par des virgules (ex: "
            "'Clérieu, AutreMarque'). Si renseigné, SEULS les produits de "
            "ces marques sont envoyés vers cette boutique Shopify (liste "
            "blanche). Laisser vide pour ne pas restreindre par marque."
        ),
    )
    export_brand_exclude = fields.Char(
        string="Exclure ces marques de l'export",
        help=(
            "Optionnel. Une ou plusieurs marques Odoo (champ 'Marque "
            "Shopify' / vendor), séparées par des virgules (ex: "
            "'Clérieu'). Si renseigné, les produits de ces marques ne "
            "sont JAMAIS envoyés vers cette boutique Shopify (liste "
            "noire), même s'ils correspondent au champ 'N'exporter QUE "
            "ces marques' ci-dessus. Laisser vide pour ne rien exclure."
        ),
    )
    sync_customers = fields.Boolean(default=True)
    sync_orders = fields.Boolean(default=True)
    sync_payments = fields.Boolean(default=True)
    sync_fulfillments = fields.Boolean(default=True)
    share_catalog = fields.Boolean(
        string="Catalogue partagé avec les autres boutiques",
        default=False,
        help=(
            "Si activé, un produit déjà importé/lié depuis une AUTRE boutique "
            "Shopify (même SKU, code-barres ou nom) est réutilisé et une "
            "liaison supplémentaire est ajoutée sur ce même produit Odoo, au "
            "lieu de créer un doublon. Utile quand plusieurs boutiques (ex. "
            "plusieurs marques) vendent tout ou partie du même catalogue. "
            "Attention : le nom, la description et l'image principale du "
            "produit restent alors partagés entre toutes les boutiques liées."
        ),
    )
    share_customers = fields.Boolean(
        string="Clients partagés avec les autres boutiques",
        default=False,
        help=(
            "Si activé, un client déjà importé/lié depuis une AUTRE boutique "
            "Shopify (même email) est réutilisé et une liaison "
            "supplémentaire est ajoutée sur ce même contact Odoo, au lieu de "
            "créer un doublon."
        ),
    )
    delivery_status_initialized = fields.Boolean(
        string="Statuts de livraison initialisés",
        default=False,
        copy=False,
        help="Technique : passe à vrai après la première mise à jour "
        "automatique des statuts de livraison de toutes les commandes.",
    )
    auto_confirm_orders = fields.Boolean(
        default=True,
        string="Confirmer automatiquement les commandes importées",
        help=(
            "Si activé, les commandes importées depuis Shopify sont "
            "automatiquement confirmées dans Odoo (comme si vous cliquiez "
            "sur 'Confirmer'), ce qui déclenche la création automatique du "
            "bon de livraison. Si désactivé, elles restent en devis et vous "
            "devez les confirmer manuellement."
        ),
    )

    # --- Suppression synchronisée (v9.7) ---
    product_delete_from_shopify = fields.Selection(
        [
            ("delete", "Supprimer aussi dans Odoo"),
            ("archive", "Archiver dans Odoo"),
            ("none", "Ne rien faire dans Odoo"),
        ],
        string="Produit supprimé dans Shopify",
        default="delete",
        required=True,
        help=(
            "Que faire dans Odoo quand un produit est supprimé dans Shopify.\n"
            "• Supprimer : le produit est supprimé d'Odoo. S'il est déjà "
            "utilisé (commandes, factures, mouvements de stock), Odoo ne "
            "peut pas le supprimer sans perdre l'historique : il est alors "
            "archivé automatiquement.\n"
            "• Archiver : le produit est seulement archivé (récupérable).\n"
            "• Ne rien faire : seul le lien avec Shopify est retiré.\n"
            "Un produit encore lié à une autre boutique n'est jamais touché."
        ),
    )
    product_delete_to_shopify = fields.Boolean(
        string="Produit supprimé dans Odoo → supprimer dans Shopify",
        default=True,
        help=(
            "Si activé, supprimer (ou archiver) un produit dans Odoo le "
            "supprime aussi de cette boutique Shopify. La suppression "
            "Shopify n'a lieu qu'une fois la suppression Odoo réussie."
        ),
    )

    default_warehouse_id = fields.Many2one("stock.warehouse", string="Entrepôt par défaut")
    order_team_id = fields.Many2one("crm.team", string="Équipe commerciale")
    default_pricelist_id = fields.Many2one("product.pricelist", string="Liste de prix")
    stock_location_id = fields.Many2one(
        "stock.location", string="Emplacement de stock source"
    )

    last_sync_products = fields.Datetime(readonly=True)
    last_sync_orders = fields.Datetime(readonly=True)
    last_sync_customers = fields.Datetime(readonly=True)

    webhook_log_ids = fields.One2many("shopify.webhook.log", "config_id")
    sync_log_ids = fields.One2many("shopify.sync.log", "config_id")
    location_ids = fields.One2many("shopify.location", "config_id", string="Emplacements Shopify")

    # --- Tableau de bord : compteurs ---
    product_count = fields.Integer(compute="_compute_dashboard_counts", string="Produits")
    customer_count = fields.Integer(compute="_compute_dashboard_counts", string="Clients")
    order_count = fields.Integer(
        compute="_compute_dashboard_counts", string="Commandes (total, tous statuts)"
    )
    sync_error_count = fields.Integer(
        compute="_compute_dashboard_counts", string="Erreurs de synchro (7 derniers jours)"
    )
    webhook_pending_count = fields.Integer(
        compute="_compute_dashboard_counts", string="Webhooks en attente"
    )

    def _compute_dashboard_counts(self):
        Product = self.env["product.template"].sudo()
        Partner = self.env["res.partner"].sudo()
        Order = self.env["sale.order"].sudo()
        SyncLog = self.env["shopify.sync.log"].sudo()
        WebhookLog = self.env["shopify.webhook.log"].sudo()
        since = fields.Datetime.now() - timedelta(days=7)
        for config in self:
            config.product_count = Product.search_count(
                [("shopify_link_ids.config_id", "=", config.id)]
            )
            config.customer_count = Partner.search_count(
                [("shopify_partner_link_ids.config_id", "=", config.id)]
            )
            config.order_count = Order.search_count(
                [("shopify_config_id", "=", config.id)]
            )
            config.sync_error_count = SyncLog.search_count(
                [
                    ("config_id", "=", config.id),
                    ("state", "=", "error"),
                    ("create_date", ">=", since),
                ]
            )
            config.webhook_pending_count = WebhookLog.search_count(
                [("config_id", "=", config.id), ("state", "=", "received")]
            )

    def action_view_shopify_products(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "shopify_odoo_connector.action_shopify_products"
        )
        action["domain"] = [("shopify_link_ids.config_id", "=", self.id)]
        return action

    def action_view_shopify_customers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Clients Shopify",
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("shopify_partner_link_ids.config_id", "=", self.id)],
        }

    def action_view_shopify_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Commandes Shopify",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("shopify_config_id", "=", self.id)],
        }

    def action_view_sync_errors(self):
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(days=7)
        return {
            "type": "ir.actions.act_window",
            "name": "Erreurs de synchronisation",
            "res_model": "shopify.sync.log",
            "view_mode": "list,form",
            "domain": [
                ("config_id", "=", self.id),
                ("state", "=", "error"),
                ("create_date", ">=", since),
            ],
        }

    _sql_constraints = [
        ("shop_url_uniq", "unique(shop_url, company_id)", "Cette boutique est déjà configurée."),
    ]

    @api.constrains("auth_type", "access_token", "client_id", "client_secret")
    def _check_auth_fields(self):
        for config in self:
            if config.auth_type == "oauth" and not (config.client_id and config.client_secret):
                raise UserError(
                    _("En mode OAuth, le Client ID et le Client Secret sont obligatoires.")
                )

    # ------------------------------------------------------------------
    # Client API
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Collection Shopify "Etsy (OrderBridge)" : contient UNIQUEMENT les
    # produits qui ont une fiche Etsy dans Odoo. Filtrer sur cette
    # collection dans OrderBridge = n'afficher que ces produits.
    # ------------------------------------------------------------------
    etsy_collection_title = fields.Char(
        string="Collection Etsy (OrderBridge)",
        default="Etsy (OrderBridge)",
        help="Collection Shopify gérée automatiquement par Odoo : un "
        "produit y est ajouté dès qu'il a une fiche Etsy dans Odoo, et "
        "retiré dès que sa fiche Etsy est supprimée. Dans OrderBridge, "
        "filtrez sur cette collection.",
    )
    etsy_collection_id = fields.Char(string="ID collection Etsy", copy=False, readonly=True)

    # ------------------------------------------------------------------
    # "Deuxième fiche" VISIBLE dans Shopify : définitions de métachamps
    # épinglées -> sur la page du produit Shopify, la carte "Métachamps"
    # affiche la fiche Amazon (Amazon – Titre, Amazon – Description,
    # Amazon – Prix...) sous la fiche Etsy (champs standards).
    # ------------------------------------------------------------------
    _SHOPIFY_FICHE_BASE_KEYS = [
        ("title", "Titre", "single_line_text_field"),
        ("description", "Description", "multi_line_text_field"),
        ("price", "Prix", "number_decimal"),
        ("category", "Catégorie", "single_line_text_field"),
        ("image_url", "Image principale (URL)", "url"),
        ("media_urls", "Photos (URLs)", "multi_line_text_field"),
    ]
    _SHOPIFY_FICHE_PLATFORM_KEYS = {
        "amazon": [
            ("bullet_points", "Points clés", "multi_line_text_field"),
            ("search_terms", "Mots-clés de recherche", "single_line_text_field"),
            ("brand", "Marque", "single_line_text_field"),
            ("product_type", "Type de produit", "single_line_text_field"),
            ("browse_node_id", "Browse node", "single_line_text_field"),
            ("condition_type", "État", "single_line_text_field"),
            ("country_of_origin", "Pays d'origine", "single_line_text_field"),
            ("safety_warning", "Avertissement sécurité", "multi_line_text_field"),
        ],
    }
    _SHOPIFY_MF_DEFINITION_MUTATION = """
        mutation($definition: MetafieldDefinitionInput!) {
          metafieldDefinitionCreate(definition: $definition) {
            createdDefinition { id }
            userErrors { field message code }
          }
        }
    """
    shopify_fiche_definitions_key = fields.Char(copy=False)

    def _shopify_fiche_definition_list(self):
        """(namespace, key, nom affiché, type) des fiches marketplace en
        mode métachamps (ex : Amazon)."""
        result = []
        marketplaces = self.env["shopify.marketplace"].sudo().search(
            [("shopify_publish_mode", "=", "metafield"), ("active", "=", True)]
        )
        for marketplace in marketplaces:
            keys = self._SHOPIFY_FICHE_BASE_KEYS + self._SHOPIFY_FICHE_PLATFORM_KEYS.get(
                marketplace.platform_type, []
            )
            for key, label, mtype in keys:
                result.append(
                    (
                        f"marketplace_{marketplace.code}",
                        key,
                        f"{marketplace.name} – {label}",
                        mtype,
                        # Seule la fiche Amazon est épinglée (visible d'office
                        # sur la page produit) ; les autres restent
                        # accessibles via « Afficher tout ».
                        marketplace.platform_type == "amazon" and self.shopify_pin_detailed_metafields,
                    )
                )
        # Dimensions produit : toujours visibles (épinglées) sur la page
        # produit Shopify.
        Template = self.env["product.template"]
        for _field, key, label in Template.SHOPIFY_DIMENSION_FIELDS:
            result.append((Template.SHOPIFY_DIMENSION_NAMESPACE, key, label, "dimension", True))
        return result

    def _shopify_ensure_fiche_definitions(self, force=False):
        """Crée (une fois) les définitions de métachamps épinglées, pour que
        la fiche Amazon s'affiche en clair sur la page produit Shopify."""
        self.ensure_one()
        definitions = self._shopify_fiche_definition_list()
        signature = hashlib.md5(repr(definitions).encode()).hexdigest()
        if not definitions or (not force and self.shopify_fiche_definitions_key == signature):
            return
        client = self.get_client()
        errors = []
        for namespace, key, name, mtype, pinned in definitions:
            for pin in ((True, False) if pinned else (False,)):
                try:
                    data = client.graphql(
                        self._SHOPIFY_MF_DEFINITION_MUTATION,
                        variables={
                            "definition": {
                                "name": name,
                                "namespace": namespace,
                                "key": key,
                                "type": mtype,
                                "ownerType": "PRODUCT",
                                "pin": pin,
                            }
                        },
                    )
                except ShopifyAPIError as exc:
                    errors.append(f"{namespace}.{key} : {exc}")
                    break
                user_errors = ((data or {}).get("metafieldDefinitionCreate") or {}).get("userErrors") or []
                codes = {e.get("code") for e in user_errors}
                if not user_errors or "TAKEN" in codes:
                    break  # créée, ou déjà existante
                if pin and ("PINNED_LIMIT_REACHED" in codes or any(
                    "pin" in (e.get("message") or "").lower() for e in user_errors
                )):
                    continue  # limite d'épinglage : on la crée non épinglée
                errors.append(f"{namespace}.{key} : {user_errors}")
                break
        if errors:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": self.id,
                    "direction": "out",
                    "model_name": "shopify.config",
                    "res_id": self.id,
                    "shopify_object_type": "metafield definitions",
                    "state": "error",
                    "message": "\n".join(errors),
                }
            )
        else:
            self.sudo().write({"shopify_fiche_definitions_key": signature})

    def action_shopify_create_fiche_definitions(self):
        """Bouton : (re)crée la fiche Amazon visible dans Shopify."""
        for config in self:
            config._shopify_ensure_fiche_definitions(force=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Shopify"),
                "message": _("Fiche Amazon créée dans Shopify (carte « Métachamps » de chaque produit)."),
                "type": "success",
            },
        }

    # ------------------------------------------------------------------
    # LISTE "Fiches marketplace" sur le produit Shopify
    # ------------------------------------------------------------------
    # Un métaobjet "Fiche marketplace" par fiche (Fiche Amazon, Fiche Etsy)
    # + un métachamp liste épinglé sur le produit. Dans l'admin Shopify,
    # la carte Métachamps affiche "Fiches marketplace : Fiche Amazon, Fiche
    # Etsy" ; un clic sur une entrée ouvre CETTE fiche.
    FICHE_METAOBJECT_TYPE = "fiche_marketplace"
    FICHE_LIST_NAMESPACE = "marketplace"
    FICHE_LIST_KEY = "fiches"
    # v4.9 : « Fiche active » = LISTE DÉROULANTE envoyée par Odoo
    # (Fiche Amazon / Fiche Etsy / ...). Ne dépend que du scope
    # write_products. L'essai v4.8 (référence de métaobjet, vide tant
    # qu'aucune fiche n'existe) est supprimé.
    FICHE_ACTIVE_KEY = "fiche_active"
    FICHE_ACTIVE_LEGACY_KEY = "fiche_selectionnee"

    @staticmethod
    def _shopify_fiche_label(marketplace):
        return f"Fiche {marketplace.name}"
    _FICHE_FIELDS = [
        ("nom", "Nom de la fiche", "single_line_text_field"),
        ("marketplace", "Marketplace", "single_line_text_field"),
        ("envoi", "Envoyée à", "single_line_text_field"),
        ("titre", "Titre", "single_line_text_field"),
        ("description", "Description", "multi_line_text_field"),
        ("prix", "Prix", "number_decimal"),
        ("image_url", "Image principale (URL)", "url"),
        ("photos", "Photos (URLs)", "multi_line_text_field"),
        ("tags", "Tags / mots-clés", "single_line_text_field"),
        ("points_cles", "Points clés", "multi_line_text_field"),
        ("details", "Détails marketplace", "multi_line_text_field"),
    ]
    shopify_fiche_metaobject_def_id = fields.Char(copy=False)
    shopify_fiche_list_ready = fields.Boolean(copy=False)  # réinitialisé en v4.7 (fiche active)
    shopify_pin_detailed_metafields = fields.Boolean(
        string="Afficher aussi les métachamps Amazon détaillés",
        default=False,
        help="En plus de la liste « Fiches marketplace », épingle chaque "
        "métachamp Amazon (Amazon – Titre, Amazon – Prix, ...) sur la page "
        "produit Shopify.",
    )

    def _shopify_graphql_checked(self, query, variables, root):
        data = self.get_client().graphql(query, variables=variables)
        payload = (data or {}).get(root) or {}
        errors = [e for e in (payload.get("userErrors") or []) if e.get("code") != "TAKEN"]
        if errors:
            raise ShopifyAPIError(f"{root} : {errors}", payload=errors)
        return payload, data

    shopify_fiche_choices_key = fields.Char(copy=False)

    def _shopify_fiche_choice_labels(self):
        return [
            self._shopify_fiche_label(m)
            for m in self.env["shopify.marketplace"].sudo().search([("active", "=", True)])
        ]

    def _shopify_ensure_fiche_choice_definition(self):
        """Crée (ou met à jour) la liste déroulante « Fiche active » du
        produit Shopify, avec les choix envoyés par Odoo (une entrée par
        marketplace : Fiche Amazon, Fiche Etsy, ...)."""
        self.ensure_one()
        labels = self._shopify_fiche_choice_labels()
        signature = hashlib.md5(json.dumps(labels).encode()).hexdigest()
        if self.shopify_fiche_choices_key == signature:
            return
        definition = {
            "name": "Fiche active",
            "description": "Fiche Etsy = contenu du produit envoyé par OrderBridge vers Etsy. "
            "Fiche Amazon = contenu envoyé vers Amazon. Choisissez puis Enregistrez : "
            "Odoo met le produit à jour en quelques secondes.",
            "namespace": self.FICHE_LIST_NAMESPACE,
            "key": self.FICHE_ACTIVE_KEY,
            "ownerType": "PRODUCT",
            "validations": [{"name": "choices", "value": json.dumps(labels)}],
        }
        data = self.get_client().graphql(
            """mutation($definition: MetafieldDefinitionInput!) {
                 metafieldDefinitionCreate(definition: $definition) {
                   createdDefinition { id } userErrors { field message code } } }""",
            variables={"definition": dict(definition, type="single_line_text_field", pin=True)},
        )
        errors = ((data or {}).get("metafieldDefinitionCreate") or {}).get("userErrors") or []
        if any(e.get("code") == "TAKEN" for e in errors):
            # Déjà créée : on met à jour la liste des choix.
            self._shopify_graphql_checked(
                """mutation($definition: MetafieldDefinitionUpdateInput!) {
                     metafieldDefinitionUpdate(definition: $definition) {
                       updatedDefinition { id } userErrors { field message code } } }""",
                {"definition": definition},
                "metafieldDefinitionUpdate",
            )
        elif errors:
            raise ShopifyAPIError(f"Définition « Fiche active » : {errors}", payload=errors)
        try:
            self._shopify_clean_product_metafield_layout()
        except ShopifyAPIError:
            _logger.warning("Nettoyage de la page produit Shopify incomplet", exc_info=True)
        self.sudo().write({"shopify_fiche_choices_key": signature})

    def _shopify_product_definitions(self, namespace):
        data = self.get_client().graphql(
            """query($ns: String!) {
                 metafieldDefinitions(first: 100, ownerType: PRODUCT, namespace: $ns) {
                   nodes { id key pinnedPosition }
                 } }""",
            variables={"ns": namespace},
        )
        return ((data or {}).get("metafieldDefinitions") or {}).get("nodes") or []

    def _shopify_clean_product_metafield_layout(self):
        """Page produit Shopify épurée : seul le sélecteur « Fiche active »
        reste épinglé. Les métachamps Amazon détaillés et la liste de
        toutes les fiches sont désépinglés (toujours consultables via
        « Tout afficher »), l'ancien champ texte « Fiche active » est
        supprimé."""
        self.ensure_one()
        unpin = """mutation($id: ID!) { metafieldDefinitionUnpin(definitionId: $id) {
                     userErrors { field message code } } }"""
        namespaces = [
            f"marketplace_{m.code}"
            for m in self.env["shopify.marketplace"].sudo().with_context(active_test=False).search([])
        ]
        if self.shopify_pin_detailed_metafields:
            namespaces = [ns for ns in namespaces if ns != "marketplace_amazon"]
        def safe(query, variables):
            try:
                self.get_client().graphql(query, variables=variables)
            except ShopifyAPIError:
                _logger.warning("Mise en page Shopify : appel ignoré", exc_info=True)

        for namespace in namespaces:
            for node in self._shopify_product_definitions(namespace):
                if node.get("pinnedPosition") is not None:
                    safe(unpin, {"id": node["id"]})
        for node in self._shopify_product_definitions(self.FICHE_LIST_NAMESPACE):
            if node.get("key") == self.FICHE_LIST_KEY and node.get("pinnedPosition") is not None:
                safe(unpin, {"id": node["id"]})
            elif node.get("key") == self.FICHE_ACTIVE_LEGACY_KEY:
                safe(
                    """mutation($id: ID!) {
                         metafieldDefinitionDelete(id: $id, deleteAllAssociatedMetafields: true) {
                           deletedDefinitionId userErrors { field message code } } }""",
                    {"id": node["id"]},
                )

    def _shopify_reset_fiche_definitions_v49(self):
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.fiche_choices_v49"
        if not param.get_param(key):
            self.sudo().with_context(active_test=False).search([]).write(
                {"shopify_fiche_list_ready": False, "shopify_fiche_choices_key": False}
            )
            param.set_param(key, "1")

    def _shopify_reset_fiche_definitions_v48(self):
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.fiche_selector_v48"
        if not param.get_param(key):
            self.sudo().with_context(active_test=False).search([]).write({"shopify_fiche_list_ready": False})
            param.set_param(key, "1")

    def _shopify_reset_fiche_definitions_v47(self):
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.fiche_active_v47"
        if not param.get_param(key):
            self.sudo().with_context(active_test=False).search([]).write({"shopify_fiche_list_ready": False})
            param.set_param(key, "1")

    def _shopify_ensure_fiche_list_definition(self):
        """Crée une fois : le type de métaobjet "Fiche marketplace" et le
        métachamp produit "Fiches marketplace" (liste, épinglé)."""
        self.ensure_one()
        if self.shopify_fiche_list_ready and self.shopify_fiche_metaobject_def_id:
            return self.shopify_fiche_metaobject_def_id
        payload, _data = self._shopify_graphql_checked(
            """
            mutation($definition: MetaobjectDefinitionCreateInput!) {
              metaobjectDefinitionCreate(definition: $definition) {
                metaobjectDefinition { id }
                userErrors { field message code }
              }
            }""",
            {
                "definition": {
                    "type": self.FICHE_METAOBJECT_TYPE,
                    "name": "Fiche marketplace",
                    "displayNameKey": "nom",
                    "fieldDefinitions": [
                        {"key": key, "name": name, "type": mtype} for key, name, mtype in self._FICHE_FIELDS
                    ],
                }
            },
            "metaobjectDefinitionCreate",
        )
        definition_id = (payload.get("metaobjectDefinition") or {}).get("id")
        if not definition_id:
            data = self.get_client().graphql(
                "query($type: String!) { metaobjectDefinitionByType(type: $type) { id } }",
                variables={"type": self.FICHE_METAOBJECT_TYPE},
            )
            definition_id = ((data or {}).get("metaobjectDefinitionByType") or {}).get("id")
        if not definition_id:
            raise ShopifyAPIError("Type de métaobjet « Fiche marketplace » introuvable.")
        self._shopify_graphql_checked(
            """
            mutation($definition: MetafieldDefinitionInput!) {
              metafieldDefinitionCreate(definition: $definition) {
                createdDefinition { id }
                userErrors { field message code }
              }
            }""",
            {
                "definition": {
                    "name": "Fiches marketplace (toutes)",
                    "description": "Fiche Amazon / Fiche Etsy de ce produit (gérées depuis Odoo). "
                    "Cliquez sur une fiche pour l'ouvrir.",
                    "namespace": self.FICHE_LIST_NAMESPACE,
                    "key": self.FICHE_LIST_KEY,
                    "type": "list.metaobject_reference",
                    "ownerType": "PRODUCT",
                    "pin": False,
                    "validations": [{"name": "metaobject_definition_id", "value": definition_id}],
                }
            },
            "metafieldDefinitionCreate",
        )
        self.sudo().write(
            {"shopify_fiche_metaobject_def_id": definition_id, "shopify_fiche_list_ready": True}
        )
        return definition_id

    def _shopify_etsy_collection_id(self, create=True):
        """ID de la collection manuelle Etsy (créée à la première
        utilisation, non publiée sur la boutique en ligne)."""
        self.ensure_one()
        if self.etsy_collection_id or not create:
            return self.etsy_collection_id
        result = self.get_client().rest_post(
            "/custom_collections.json",
            {
                "custom_collection": {
                    "title": self.etsy_collection_title or "Etsy (OrderBridge)",
                    "published": False,
                }
            },
        )
        collection_id = str((result.get("custom_collection") or {}).get("id") or "")
        if collection_id:
            self.sudo().write({"etsy_collection_id": collection_id})
        return collection_id

    def get_client(self):
        self.ensure_one()
        if not self.access_token:
            raise UserError(
                _(
                    "La boutique %s n'est pas encore authentifiée. Renseignez le token "
                    "d'accès Admin API (mode Token direct) ou connectez-vous via OAuth."
                )
                % self.name
            )
        return ShopifyAPIClient(self.shop_url, self.access_token, self.api_version)

    # ------------------------------------------------------------------
    # Authentification par token direct (App personnalisée) - RECOMMANDÉ
    # ------------------------------------------------------------------
    def action_connect_private(self):
        """Valide le token d'accès saisi manuellement, puis termine la
        configuration (webhooks + emplacements) sans passer par OAuth."""
        self.ensure_one()
        if not self.access_token:
            raise UserError(
                _(
                    "Veuillez d'abord renseigner le token d'accès Admin API "
                    "obtenu depuis votre app personnalisée Shopify."
                )
            )
        client = self.get_client()
        try:
            shop_info = client.rest_get("/shop.json")
        except ShopifyAPIError as exc:
            self.write({"state": "error", "last_error": str(exc)})
            raise UserError(str(exc))

        self.write({"state": "connected", "last_error": False})
        self._register_webhooks()
        self._sync_locations()
        self.message_post(
            body=_("Connexion réussie à la boutique : %s")
            % shop_info.get("shop", {}).get("name")
        )
        self._run_initial_full_import()

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    def action_connect_oauth(self):
        """Génère l'URL d'autorisation Shopify et redirige l'utilisateur."""
        self.ensure_one()
        if self.auth_type != "oauth":
            raise UserError(
                _("Passez d'abord le mode d'authentification sur 'OAuth' pour utiliser ce bouton.")
            )
        if not (self.client_id and self.client_secret):
            raise UserError(_("Renseignez le Client ID et le Client Secret avant de vous connecter."))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        redirect_uri = f"{base_url}/shopify/oauth/callback"
        state = secrets.token_urlsafe(24)
        self.oauth_state = state
        authorize_url = ShopifyAPIClient.build_authorize_url(
            self.shop_url, self.client_id, redirect_uri, self.scope, state
        )
        return {
            "type": "ir.actions.act_url",
            "url": authorize_url,
            "target": "self",
        }

    def _oauth_complete(self, code):
        """Appelée par le contrôleur juste après réception du 'code' OAuth.

        IMPORTANT : ne fait QUE l'échange du code contre un access_token
        et l'enregistrement de celui-ci. Le `code` OAuth Shopify est à
        usage unique et expire très vite : si cette méthode restait
        bloquée ensuite sur l'enregistrement des webhooks, la synchro
        des emplacements et l'import initial complet (potentiellement
        long), la requête HTTP du callback risquerait de dépasser le
        timeout du proxy/reverse-proxy (odoo.sh, nginx, ...). Un tel
        timeout déclenche souvent un retry automatique de la même
        requête GET côté proxy ou navigateur, qui soumettrait alors le
        même `code` une seconde fois à Shopify -> erreur Shopify
        "The authorization code was not found or was already used",
        même quand le premier échange avait réussi et que les
        identifiants sont corrects.

        Le reste de la configuration (webhooks, emplacements, import
        initial) est donc planifié en tâche de fond juste après, une
        fois le token déjà sauvegardé en base."""
        self.ensure_one()
        token_data = ShopifyAPIClient.exchange_code_for_token(
            self.shop_url, self.client_id, self.client_secret, code
        )
        self.write(
            {
                "access_token": token_data.get("access_token"),
                "state": "connected",
                "last_error": False,
            }
        )
        # Le token est sauvegardé : on committe tout de suite pour ne
        # jamais risquer de le perdre si la suite (planifiée ci-dessous)
        # échoue ou si le contrôleur est interrompu après ce point.
        self.env.cr.commit()
        self._schedule_post_oauth_setup()

    shopify_post_oauth_pending = fields.Boolean(
        string="Finalisation de connexion en attente", copy=False, readonly=True
    )

    def _schedule_post_oauth_setup(self):
        """Planifie l'enregistrement des webhooks, la synchro des emplacements
        et l'import initial complet en arrière-plan, pour que le contrôleur
        OAuth réponde immédiatement (voir _oauth_complete).

        v9.13 : on ne crée PLUS un ir.cron par boutique qui se désactive
        lui-même. Un job qui modifie sa propre ligne ir_cron pendant son
        exécution entre en conflit avec le verrou que le planificateur tient
        sur cette ligne : le job restait bloqué indéfiniment sur
        « ... (58) starting », ou bien l'écriture échouait, la transaction
        était annulée, le cron restait actif et relançait l'import complet
        chaque minute. Désormais : un simple drapeau sur la boutique + UNE
        tâche planifiée permanente, déclenchée immédiatement (_trigger)."""
        self.ensure_one()
        self.sudo().write({"shopify_post_oauth_pending": True})
        cron = self.env.ref(
            "shopify_odoo_connector.cron_shopify_post_oauth_setup", raise_if_not_found=False
        )
        if cron:
            cron.sudo()._trigger()

    @api.model
    def cron_run_post_oauth_setup(self):
        """Traite les boutiques dont la finalisation de connexion est en attente.
        Le drapeau est retiré et COMMITTÉ avant tout travail : même si le
        worker est tué (limit_time_real_cron) en plein import, rien ne se
        relance en boucle."""
        for config in self.search([("shopify_post_oauth_pending", "=", True)]):
            config.write({"shopify_post_oauth_pending": False})
            self.env.cr.commit()
            config._run_post_oauth_setup()

    def _run_post_oauth_setup(self, cron_id=None):
        """Webhooks, emplacements, puis import initial complet. Chaque étape
        est enregistrée séparément : une erreur sur l'une n'annule pas les
        autres. (`cron_id` conservé pour compatibilité, ignoré.)"""
        self.ensure_one()
        for label, step in (
            ("webhooks", self._register_webhooks),
            ("emplacements", self._sync_locations),
        ):
            try:
                with self.env.cr.savepoint():
                    step()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception("Finalisation connexion (%s) en erreur pour %s", label, self.name)
        self.message_post(body=_("Connexion OAuth Shopify réussie."))
        self.env.cr.commit()
        self._run_initial_full_import()
        self.env.cr.commit()

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def _register_webhooks(self):
        self.ensure_one()
        client = self.get_client()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        callback_url = f"{base_url}/shopify/webhook"

        existing = client.rest_get("/webhooks.json").get("webhooks", [])
        existing_topics = {w["topic"]: w for w in existing}

        for topic in WEBHOOK_TOPICS:
            if topic in existing_topics:
                hook = existing_topics[topic]
                if hook.get("address") != callback_url:
                    # Adresse périmée (ex : nouvelle URL ngrok après
                    # redémarrage) : Shopify envoyait les notifications dans
                    # le vide. On corrige l'adresse.
                    try:
                        client.rest_put(
                            f"/webhooks/{hook['id']}.json",
                            {"webhook": {"id": hook["id"], "address": callback_url}},
                        )
                        _logger.info("Webhook %s corrigé : %s -> %s", topic, hook.get("address"), callback_url)
                    except ShopifyAPIError as exc:
                        _logger.error("Impossible de corriger le webhook %s : %s", topic, exc)
                continue
            try:
                client.rest_post(
                    "/webhooks.json",
                    {
                        "webhook": {
                            "topic": topic,
                            "address": callback_url,
                            "format": "json",
                        }
                    },
                )
                _logger.info("Webhook Shopify enregistré : %s pour %s", topic, self.shop_url)
            except ShopifyAPIError as exc:
                _logger.error("Impossible d'enregistrer le webhook %s : %s", topic, exc)

    # ------------------------------------------------------------------
    # « Fiche active » : vérification CONTINUE (toutes les minutes), même
    # si le webhook n'arrive pas (URL ngrok changée, notification perdue,
    # Shopify qui n'envoie pas de notification pour un métachamp...).
    # ------------------------------------------------------------------
    shopify_webhooks_checked_at = fields.Datetime(copy=False)

    @api.model
    def cron_poll_fiche_active(self):
        for config in self.search([("state", "=", "connected")]):
            try:
                config._shopify_poll_fiche_active()
            except Exception:  # noqa: BLE001
                _logger.exception("Vérification « Fiche active » impossible (%s)", config.display_name)
            # Réparation automatique des webhooks (au plus toutes les 10 min).
            if not config.shopify_webhooks_checked_at or (
                fields.Datetime.now() - config.shopify_webhooks_checked_at
            ) > timedelta(minutes=10):
                try:
                    config._register_webhooks()
                except Exception:  # noqa: BLE001
                    _logger.exception("Vérification des webhooks impossible (%s)", config.display_name)
                config.sudo().write({"shopify_webhooks_checked_at": fields.Datetime.now()})
            self.env.cr.commit()

    def _shopify_poll_fiche_active(self):
        """Lit en UNE requête (par lot de 250 produits) la « Fiche active »
        choisie dans Shopify et applique tout changement dans Odoo."""
        self.ensure_one()
        links = self.env["shopify.product.link"].sudo().search(
            [("config_id", "=", self.id), ("shopify_product_id", "!=", False)]
        ).filtered(lambda l: l.product_tmpl_id.shopify_marketplace_content_ids)
        by_gid = {f"gid://shopify/Product/{l.shopify_product_id}": l.product_tmpl_id for l in links}
        gids = list(by_gid)
        changed = self.env["product.template"]
        for start in range(0, len(gids), 250):
            data = self.get_client().graphql(
                """query($ids: [ID!]!) { nodes(ids: $ids) { ... on Product {
                     id metafield(namespace: "%s", key: "%s") { value } } } }"""
                % (self.FICHE_LIST_NAMESPACE, self.FICHE_ACTIVE_KEY),
                variables={"ids": gids[start:start + 250]},
            )
            for node in (data or {}).get("nodes") or []:
                if not node:
                    continue
                template = by_gid.get(node.get("id"))
                label = ((node.get("metafield") or {}).get("value") or "").strip()
                if not template or not label or template.shopify_switch_pending or template.shopify_push_pending:
                    continue
                current = template._shopify_main_content()
                if current and self._shopify_fiche_label(current.marketplace_id) == label:
                    continue
                chosen = template.shopify_marketplace_content_ids.filtered(
                    lambda c: self._shopify_fiche_label(c.marketplace_id) == label
                )[:1]
                if not chosen:
                    continue
                template.with_context(shopify_sync=True).write(
                    {"shopify_active_marketplace_id": chosen.marketplace_id.id}
                )
                changed |= template
        for template in changed:
            template._shopify_switch_fiche_now()

    def action_shopify_apply_fiches_now(self):
        """Bouton : applique tout de suite les « Fiche active » choisies dans
        Shopify et répare l'adresse des webhooks."""
        for config in self:
            config._register_webhooks()
            config._shopify_poll_fiche_active()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "Shopify", "message": "Fiches actives appliquées, webhooks vérifiés.", "type": "success"},
        }

    def action_resync_webhooks(self):
        for config in self:
            config._register_webhooks()

    @api.model
    def _shopify_migrate_scopes(self):
        """Ajoute aux boutiques existantes les autorisations (scopes)
        ajoutées depuis leur création (ex : read_metaobjects, nécessaires à
        la liste « Fiches marketplace »). Le champ `scope` n'avait reçu la
        valeur par défaut qu'à la création de la boutique. Il faut ensuite
        RECONNECTER la boutique pour que Shopify accorde ces droits."""
        wanted = [s.strip() for s in DEFAULT_SCOPES.split(",") if s.strip()]
        for config in self.sudo().search([]):
            current = [s.strip() for s in (config.scope or "").split(",") if s.strip()]
            missing = [s for s in wanted if s not in current]
            if missing:
                config.with_context(shopify_sync=True).write({"scope": ",".join(current + missing)})
                _logger.warning(
                    "Boutique %s : autorisations ajoutées %s. Reconnectez la "
                    "boutique pour que Shopify les accorde.",
                    config.name, ", ".join(missing),
                )

    @api.model
    def _shopify_migrate_reset_guessed_categories(self):
        """Une seule fois : oublie les catégories Shopify choisies par
        l'ancienne recherche approximative, pour qu'elles soient
        recherchées à nouveau (correspondance exacte) au prochain envoi."""
        param = self.env["ir.config_parameter"].sudo()
        key = "shopify_odoo_connector.category_strict_match_migrated"
        if param.get_param(key):
            return
        contents = self.env["shopify.product.marketplace.content"].sudo().search(
            [("shopify_category_gid", "!=", False)]
        )
        contents.with_context(shopify_sync=True).write(
            {"shopify_category_gid": False, "shopify_category_fullname": False,
             "shopify_category_source": False}
        )
        templates = contents.product_tmpl_id
        if templates:
            templates._shopify_queue_push()
        param.set_param(key, "1")

    def action_load_taxonomy(self):
        """Bouton : (re)charge la liste des catégories Shopify dans Odoo
        (fichier livré avec le module : rapide, sans appel à Shopify), puis
        lance en arrière-plan une mise à jour depuis la source officielle."""
        self.ensure_one()
        Taxonomy = self.env["shopify.taxonomy.category"].sudo()
        count = Taxonomy.shopify_load_taxonomy()
        Taxonomy._shopify_trigger_taxonomy_load()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Catégories Shopify"),
                "message": _("%s catégories Shopify disponibles dans Odoo.") % count,
                "type": "success",
            },
        }

    def action_sync_diagnostic(self):
        """Bouton « Diagnostic synchro » : dit pourquoi les modifications
        Shopify n'arrivent pas dans Odoo, et lance l'import tout de suite."""
        self.ensure_one()
        lines = []
        module = self.env["ir.module.module"].sudo().search([("name", "=", "shopify_odoo_connector")], limit=1)
        lines.append(_("Version du module : %s") % (module.latest_version or "?"))
        cron = self.env.ref("shopify_odoo_connector.cron_shopify_products_fast", raise_if_not_found=False)
        if not cron or not cron.active:
            lines.append(_("PROBLÈME : la tâche « Shopify : synchronisation automatique » est désactivée."))
        else:
            lines.append(_("Tâche automatique : active, toutes les %(n)s %(u)s, prochaine exécution %(next)s, dernière %(last)s.") % {
                "n": cron.interval_number, "u": cron.interval_type, "next": cron.nextcall,
                "last": cron.lastcall or _("JAMAIS"),
            })
            if not cron.lastcall or (fields.Datetime.now() - cron.lastcall) > timedelta(minutes=30):
                lines.append(_(
                    "PROBLÈME : la tâche ne s'exécute pas. Vérifiez que le serveur "
                    "Odoo n'est pas lancé avec --max-cron-threads=0 (ou "
                    "max_cron_threads = 0 dans odoo.conf)."
                ))
        lines.append(_("Boutique : état %(state)s, produits synchronisés : %(p)s.") % {
            "state": self.state, "p": _("oui") if self.sync_products else _("NON (case à cocher)"),
        })
        lines.append(_("Dernière synchro produits : %s") % (self.last_sync_products or _("jamais")))
        outcomes = []
        try:
            self.env["product.template"].sudo().with_context(shopify_outcomes=outcomes).shopify_import_all(
                self, updated_at_min=fields.Datetime.now() - timedelta(days=1)
            )
            n_variants = self.env["product.template"].sudo().shopify_import_changed_variants(
                self, fields.Datetime.now() - timedelta(days=1)
            )
            lines.append(_("Produits modifiés dans Shopify ces dernières 24 h : %s") % len(outcomes))
            lines.append(_("Produits dont une variante (prix...) a changé ces dernières 24 h : %s — réappliqués dans Odoo.") % n_variants)
            summary = {}
            for outcome, pid, title in outcomes:
                summary.setdefault(outcome, []).append(title or pid)
            for outcome, titles in summary.items():
                sample = ", ".join(titles[:3]) + ("…" if len(titles) > 3 else "")
                lines.append(f"• {outcome} : {len(titles)} ({sample})")
        except Exception as exc:  # noqa: BLE001
            lines.append(_("PROBLÈME à l'import : %s") % exc)
        last_errors = self.env["shopify.sync.log"].sudo().search(
            [("config_id", "=", self.id), ("state", "=", "error")], limit=3
        )
        for log in last_errors:
            lines.append(_("Dernière erreur : %s") % (log.message or "")[:200])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Diagnostic synchronisation Shopify"),
                       "message": "\n".join(lines), "type": "info", "sticky": True,
                       "className": "o_shopify_notif"},
        }

    def action_check_scopes(self):
        """Bouton : compare les autorisations réellement accordées par
        Shopify au jeton avec celles dont le module a besoin."""
        self.ensure_one()
        client = self.get_client()
        data = client._safe_json(
            requests.get(
                f"https://{client.shop_url}/admin/oauth/access_scopes.json",
                headers=client._headers(),
                timeout=client.timeout,
            )
        )
        granted = {s.get("handle") for s in data.get("access_scopes", [])}
        wanted = {s.strip() for s in DEFAULT_SCOPES.split(",") if s.strip()}
        # write_x implique read_x côté Shopify
        missing = sorted(
            s for s in wanted
            if s not in granted and not (s.startswith("read_") and "write_" + s[5:] in granted)
        )
        if missing:
            message = _(
                "Autorisations manquantes : %s. Cliquez sur « Connecter » pour "
                "réautoriser l'application (ou, pour une application "
                "personnalisée, ajoutez-les dans Shopify > Paramètres > "
                "Applications > Développer des applications, puis réinstallez)."
            ) % ", ".join(missing)
            kind = "warning"
        else:
            message = _("Toutes les autorisations nécessaires sont accordées.")
            kind = "success"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Autorisations Shopify"), "message": message,
                       "type": kind, "sticky": bool(missing)},
        }

    def action_resync_locations(self):
        for config in self:
            config._sync_locations()

    # ------------------------------------------------------------------
    # Locations (emplacements Shopify <-> entrepôts Odoo)
    # ------------------------------------------------------------------
    def _shopify_ensure_own_warehouse(self):
        """Stock SÉPARÉ par boutique : chaque boutique a son propre entrepôt
        Odoo (ex : « VONROSS »). Si la boutique n'a pas d'entrepôt, ou
        partage celui d'une autre boutique, un entrepôt à son nom est créé
        et ses emplacements Shopify y sont rattachés. La boutique la plus
        ancienne garde l'entrepôt existant."""
        Warehouse = self.env["stock.warehouse"].sudo()
        oldest = self.sudo().search([("active", "=", True)], order="id asc", limit=1)
        for config in self:
            current = config.default_warehouse_id or config.location_ids.warehouse_id[:1]
            if config == oldest:
                # Boutique principale (CLERIEU) : garde son entrepôt actuel,
                # ou l'entrepôt principal de la société.
                if not current:
                    current = Warehouse.search(
                        [("company_id", "=", (config.company_id or self.env.company).id)], limit=1
                    )
                if current and config.default_warehouse_id != current:
                    config.default_warehouse_id = current
                    config.location_ids.filtered(lambda l: not l.warehouse_id).write(
                        {"warehouse_id": current.id}
                    )
                continue
            others = self.sudo().search([("id", "!=", config.id), ("active", "=", True)])
            used_by_others = others.mapped("default_warehouse_id") | others.location_ids.warehouse_id
            if current and current not in used_by_others:
                if config.default_warehouse_id != current:
                    config.default_warehouse_id = current
                continue
            company = config.company_id or self.env.company
            name = (config.name or config.shop_url or "Shopify").replace("Boutique ", "").strip()
            existing = Warehouse.search([("name", "=", name), ("company_id", "=", company.id)], limit=1)
            if not existing:
                base = "".join(c for c in _shopify_brand_key(name).upper() if c.isalnum())[:5] or "SHOP"
                code, n = base, 1
                while Warehouse.with_context(active_test=False).search_count(
                    [("code", "=", code), ("company_id", "=", company.id)]
                ):
                    code = f"{base[:4]}{n}"
                    n += 1
                existing = Warehouse.create({"name": name, "code": code, "company_id": company.id})
            config.default_warehouse_id = existing
            config.location_ids.write({"warehouse_id": existing.id})
            config.message_post(
                body=_("Entrepôt dédié « %s » créé : le stock de cette boutique est séparé des autres boutiques.")
                % existing.display_name
            )

    def _sync_locations(self):
        self.ensure_one()
        if not self.default_warehouse_id:
            # Nouvelle boutique : son propre entrepôt (stock séparé).
            self._shopify_ensure_own_warehouse()
        client = self.get_client()
        locations = client.rest_get("/locations.json").get("locations", [])
        Location = self.env["shopify.location"].sudo()
        for loc in locations:
            existing = Location.search(
                [("shopify_location_id", "=", str(loc["id"])), ("config_id", "=", self.id)]
            )
            values = {
                "config_id": self.id,
                "shopify_location_id": str(loc["id"]),
                "name": loc.get("name"),
            }
            if existing:
                existing.write(values)
            else:
                # Si un entrepôt par défaut est défini sur la boutique, on
                # l'associe automatiquement au nouvel emplacement Shopify
                # pour éviter d'avoir à le faire manuellement.
                if self.default_warehouse_id:
                    values["warehouse_id"] = self.default_warehouse_id.id
                Location.create(values)

    # ------------------------------------------------------------------
    # Actions manuelles de synchronisation complète (boutons UI)
    # ------------------------------------------------------------------
    @api.model
    def _shopify_brand_keys(self):
        """Marques de CETTE boutique : le champ « Marque(s) de cette
        boutique » + le nom de la boutique dans Odoo + le nom de la
        boutique Shopify (vonros.myshopify.com -> VONROS). Ainsi un
        produit de marque « VONROS » va sur la boutique VONROS même si le
        champ contient « VONROSS »."""
        self.ensure_one()
        keys = {
            _shopify_brand_key(b)
            for b in (self.export_brand_filter or "").split(",")
            if b.strip()
        }
        keys.add(_shopify_brand_key(self.name))
        subdomain = (self.shop_url or "").replace("https://", "").replace("http://", "").split(".")[0]
        keys.add(_shopify_brand_key(subdomain))
        keys.discard("")
        return keys

    def _shopify_brand_filter_keys(self):
        """Liste blanche d'export/import : vide si la boutique n'a pas de
        marque définie (= toutes les marques acceptées, comportement
        d'origine), sinon les marques de la boutique."""
        self.ensure_one()
        if not (self.export_brand_filter or "").strip():
            return set()
        return self._shopify_brand_keys()

    @api.model
    def _shopify_all_shop_brand_keys(self):
        keys = set()
        for config in self.sudo().search([("active", "=", True)]):
            keys |= config._shopify_brand_keys()
        return keys

    @api.model
    def _shopify_brand_shops(self):
        """Boutiques qui reçoivent les produits de leur marque."""
        return self.sudo().search(
            [("active", "=", True), ("sync_products", "=", True), ("state", "=", "connected")]
        )

    @api.model
    def _shopify_configs_for_brand(self, vendor):
        """Boutique(s) de cette marque : CLERIEU -> boutique CLERIEU,
        VONROS -> boutique VONROS."""
        key = _shopify_brand_key(vendor)
        if not key:
            return self.browse()
        return self._shopify_brand_shops().filtered(lambda c: key in c._shopify_brand_keys())

    @api.model
    def _shopify_migrate_shop_brands(self):
        """Renseigne automatiquement la marque de chaque boutique d'après
        son nom / son adresse (CLERIEU, VONROSS) si elle n'est pas encore
        définie (ou laissée à la valeur par défaut « Clérieu » sur une
        boutique qui n'est pas Clérieu)."""
        for config in self.sudo().search([]):
            ident = _shopify_brand_key(f"{config.name or ''} {config.shop_url or ''}")
            current = _shopify_brand_key(config.export_brand_filter)
            if "cler" in ident:
                wanted = "CLERIEU"
            elif "vonros" in ident:
                wanted = "VONROS, VONROSS"
            elif "unitlab" in ident:
                wanted = "UNITLAB"
            else:
                continue
            if current == _shopify_brand_key(wanted):
                continue  # déjà bon
            # Vide, ou valeur par défaut d'une version précédente.
            if not current or current == "vonross" or (current == "clerieu" and wanted != "CLERIEU"):
                config.export_brand_filter = wanted

    @api.model
    def _shopify_shops_for_brand(self, vendor):
        """Boutique(s) dont la marque est `vendor`, connectées ou non
        (CLERIEU -> boutique CLERIEU, VONROS -> boutique VONROSS…)."""
        key = _shopify_brand_key(vendor)
        if not key:
            return self.browse()
        return self.sudo().search([("active", "=", True)]).filtered(
            lambda c: key in c._shopify_brand_keys()
        )

    def _shopify_check_products_of_my_brand(self):
        """Boutique créée ou marque de boutique modifiée : les produits de
        cette marque sont automatiquement cochés pour cette boutique."""
        Template = self.env["product.template"].sudo().with_context(shopify_sync=True)
        for config in self:
            keys = config._shopify_brand_keys()
            templates = Template.search(
                [("shopify_vendor", "!=", False), ("default_code", "!=", "SHOPIFY-CUSTOM")]
            ).filtered(
                lambda t: _shopify_brand_key(t.shopify_vendor) in keys
                and config not in t.shopify_target_config_ids
            )
            if templates:
                templates.write({"shopify_target_config_ids": [(4, config.id)]})

    def _shopify_default_config(self):
        """Renvoie la config Shopify à utiliser pour pousser automatiquement
        un produit/une commande créé(e) dans Odoo, quand aucune boutique
        n'a été choisie explicitement sur l'enregistrement. On ne le fait
        que s'il existe exactement UNE boutique active : dès qu'il y en a
        plusieurs, l'ambiguïté est trop grande pour deviner la bonne. Pour
        lier un produit/client existant à une boutique en particulier (ou à
        une boutique supplémentaire), ajoutez une ligne dans l'onglet
        Shopify de sa fiche plutôt que de compter sur ce mécanisme
        automatique."""
        configs = self.search([("active", "=", True)])
        return configs if len(configs) == 1 else self.browse()

    def action_sync_products_now(self):
        """Bouton « Synchroniser les produits ».

        v9.15 : affiche un COMPTE RENDU. Avant, le bouton ne disait rien :
        impossible de savoir si Shopify avait répondu, combien de produits
        étaient arrivés, ni pourquoi un produit n'était pas importé."""
        self.ensure_one()
        lines = []
        problems = []
        if not self.access_token:
            problems.append(_("Jeton d'accès (access token) vide : reconnectez la boutique."))
        if self.state != "connected":
            problems.append(_(
                "La boutique n'est pas à l'état « Connecté » (état actuel : %s) : la synchro "
                "automatique est arrêtée pour cette boutique."
            ) % (dict(self._fields["state"].selection).get(self.state) or self.state))
        if not self.sync_products:
            problems.append(_("La case « Synchroniser les produits » est décochée : la synchro automatique ne lit pas les produits."))
        started = fields.Datetime.now()
        outcomes = []
        # Capture des erreurs SQL / serveur pendant l'import : affichées dans
        # le compte rendu (sinon visibles seulement dans le journal serveur).
        captured = []

        class _Capture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR and len(captured) < 5:
                    try:
                        msg = record.getMessage()
                    except Exception:  # noqa: BLE001
                        msg = str(record.msg)
                    if record.exc_info and record.exc_info[1]:
                        msg += " — " + str(record.exc_info[1])
                    captured.append(msg[:600])

        handler = _Capture()
        watched = [logging.getLogger("odoo.sql_db"), logging.getLogger("odoo.addons.shopify_odoo_connector")]
        for lg in watched:
            lg.addHandler(handler)
        try:
            # 1) Produits seuls, enregistrés tout de suite.
            self.env["product.template"].sudo().with_context(
                shopify_outcomes=outcomes, shopify_skip_inventory=True
            ).shopify_import_all(self)
            self.env.cr.commit()
            # 2) Stock ensuite, à part : une erreur de stock n'annule plus
            #    les produits.
            if self.sync_inventory:
                try:
                    with self.env.cr.savepoint():
                        self.env["product.product"].sudo().shopify_import_inventory_levels(self)
                    self.env.cr.commit()
                except Exception as exc:  # noqa: BLE001
                    self.env.cr.rollback()
                    problems.append(_("Produits enregistrés, mais l'import du STOCK a échoué : %s") % str(exc)[:400])
        except ShopifyAPIError as exc:
            self.env.cr.rollback()
            code = getattr(exc, "status_code", None)
            hint = {
                401: _("jeton d'accès refusé par Shopify (expiré ou révoqué) : reconnectez la boutique ou recollez le jeton."),
                402: _("boutique Shopify bloquée ou abonnement impayé."),
                403: _("autorisation manquante : l'app Shopify doit avoir « read_products » et « write_products » (bouton « Vérifier les autorisations »)."),
                404: _("boutique introuvable : vérifiez le « Domaine boutique » (ex : monshop.myshopify.com)."),
                423: _("boutique Shopify verrouillée."),
            }.get(code, _("voir le détail ci-dessous."))
            problems.insert(0, _("SHOPIFY A REFUSÉ LA LECTURE DES PRODUITS (%(code)s) : %(hint)s") % {"code": code or "réseau", "hint": hint})
            problems.append(str(exc)[:400])
        except Exception as exc:  # noqa: BLE001
            self.env.cr.rollback()
            problems.insert(0, _("ERREUR ODOO pendant l'import (rien n'a été enregistré) : %s") % str(exc)[:400])
        finally:
            for lg in watched:
                lg.removeHandler(handler)
        if captured:
            problems.append(_("Erreurs détectées sur le serveur (cause exacte) :"))
            problems += ["   ✗ " + c for c in captured]
        received = len(outcomes)
        lines.append(_("Produits lus dans Shopify : %s") % received)
        summary = {}
        for outcome, pid, title in outcomes:
            summary.setdefault(outcome, []).append(title or pid)
        for outcome, titles in sorted(summary.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(titles[:3]) + ("…" if len(titles) > 3 else "")
            lines.append(f"• {outcome} : {len(titles)} ({sample})")
        errors = self.env["shopify.sync.log"].sudo().search(
            [("config_id", "=", self.id), ("state", "=", "error"), ("create_date", ">=", started),
             ("message", "not ilike", "NON importé dans Odoo")],
            order="id desc", limit=5,
        )
        if errors:
            lines.append(_("Erreurs pendant l'import :"))
            for log in errors:
                lines.append("   ✗ " + (log.message or "")[:250])
        if received == 0 and not errors and not any("REFUSÉ" in p for p in problems):
            problems.append(_(
                "Shopify n'a renvoyé AUCUN produit : vérifiez que le jeton correspond bien à "
                "cette boutique et que l'app a l'autorisation « read_products »."
            ))
        ok = not problems and not errors
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Synchronisation des produits — compte rendu"),
                "message": "\n".join(problems + ([""] if problems else []) + lines),
                "type": "success" if ok else "warning",
                "sticky": True,
                "className": "o_shopify_notif",
            },
        }

    def _shopify_enforce_brand_filter(self):
        """Fait respecter automatiquement les filtres de marque
        (export_brand_filter / export_brand_exclude) directement sur
        Shopify : scanne TOUT le catalogue de la boutique (pas
        seulement les produits déjà connus/liés dans Odoo, car un
        produit peut avoir été créé directement dans Shopify, via son
        admin ou son app Point de vente) et ARCHIVE sur Shopify tout
        produit dont la marque ('vendor') ne correspond pas au filtre.

        Appelée automatiquement par la tâche planifiée
        (cron_sync_all_connected), sans aucune action manuelle requise.
        Ne fait rien si la boutique n'a aucun filtre de marque
        configuré (comportement d'origine, tout est autorisé)."""
        self.ensure_one()
        if not (self.export_brand_filter or "").strip() and not (self.export_brand_exclude or "").strip():
            return
        Template = self.env["product.template"].sudo()
        Link = self.env["shopify.product.link"].sudo()
        client = self.get_client()
        # status=active,draft : on ne retouche pas ce qui est déjà archivé.
        products = client.rest_get_with_pagination(
            "/products.json", params={"limit": 250, "status": "active,draft"}
        )
        archived, errors = 0, 0
        for shopify_product in products:
            vendor = (shopify_product.get("vendor") or "").strip()
            if Template._shopify_vendor_matches_config_filter(vendor, self):
                continue
            shopify_product_id = str(shopify_product.get("id"))
            link = Link.search(
                [("shopify_product_id", "=", shopify_product_id), ("config_id", "=", self.id)],
                limit=1,
            )
            if link:
                # Produit géré depuis Odoo : c'est la case « Afficher sur
                # les boutiques » du produit qui décide, pas la marque.
                continue
            try:
                with self.env.cr.savepoint():
                    client.rest_put(
                        f"/products/{shopify_product_id}.json",
                        {"product": {"id": int(shopify_product_id), "status": "archived"}},
                    )
                    archived += 1
                    self.env["shopify.sync.log"].create(
                        {
                            "config_id": self.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": link.product_tmpl_id.id if link else False,
                            "shopify_object_type": "product",
                            "shopify_object_id": shopify_product_id,
                            "state": "success",
                            "message": _(
                                "Produit archivé automatiquement sur "
                                "Shopify : marque '%s' non autorisée par "
                                "les filtres de marque de la boutique "
                                "(titre Shopify : %s)."
                            )
                            % (vendor, shopify_product.get("title")),
                        }
                    )
                    # S'il était par ailleurs lié à un produit Odoo, on
                    # retire aussi le lien pour rester cohérent avec le
                    # filtre d'import.
                    if link:
                        link.unlink()
            except Exception as exc:  # noqa: BLE001
                errors += 1
                _logger.exception(
                    "Erreur archivage automatique Shopify du produit %s (boutique %s)",
                    shopify_product_id,
                    self.display_name,
                )
                self.env["shopify.sync.log"].create(
                    {
                        "config_id": self.id,
                        "direction": "out",
                        "model_name": "product.template",
                        "res_id": link.product_tmpl_id.id if link else False,
                        "shopify_object_type": "product",
                        "shopify_object_id": shopify_product_id,
                        "state": "error",
                        "message": str(exc),
                    }
                )
        if archived or errors:
            _logger.info(
                "Filtre de marque Shopify (boutique %s) : %s produit(s) "
                "archivé(s), %s erreur(s).",
                self.display_name,
                archived,
                errors,
            )

    def action_sync_categories_now(self):
        """Rattrapage : applique la catégorie Shopify aux produits DÉJÀ
        importés/liés à cette boutique, sans refaire un import complet.
        Utile juste après avoir activé la synchronisation des catégories,
        ou après une correction de mapping."""
        self.ensure_one()
        Template = self.env["product.template"].sudo()
        links = self.env["shopify.product.link"].sudo().search(
            [("config_id", "=", self.id)]
        )
        for link in links:
            try:
                with self.env.cr.savepoint():
                    Template._shopify_sync_category(
                        link.product_tmpl_id, link.shopify_product_id, self
                    )
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Erreur lors du rattrapage de catégorie pour le produit %s",
                    link.shopify_product_id,
                )

    def action_sync_customers_now(self):
        self.ensure_one()
        self.env["res.partner"].sudo().shopify_import_all(self)

    def action_sync_orders_now(self):
        self.ensure_one()
        self.env["sale.order"].sudo().shopify_import_all(self)

    def _shopify_refresh_delivery_statuses(self, orders=None):
        """Relit dans Shopify le statut de traitement / livraison.

        - orders=None : toutes les commandes de la boutique (premier passage).
        - orders=<sale.order> : uniquement ces commandes, par lots de 250
          (1 seul appel Shopify par lot grâce au paramètre « ids »).
        Retourne le nombre de commandes Odoo mises à jour."""
        self.ensure_one()
        Order = self.env["sale.order"].sudo()
        client = self.get_client()
        base_params = {
            "limit": 250,
            "status": "any",
            "fields": "id,fulfillment_status,fulfillments",
        }
        if orders is None:
            shopify_orders = client.rest_get_with_pagination(
                "/orders.json", params=base_params, limit_pages=200
            )
        else:
            shopify_orders = []
            ids = [o.shopify_order_id for o in orders if o.shopify_order_id]
            for i in range(0, len(ids), 250):
                params = dict(base_params, ids=",".join(ids[i:i + 250]))
                shopify_orders += client.rest_get("/orders.json", params=params).get("orders", [])

        updated = 0
        for data in shopify_orders:
            order = Order.search(
                [
                    ("shopify_order_id", "=", str(data.get("id"))),
                    ("shopify_config_id", "=", self.id),
                ],
                limit=1,
            )
            if order:
                order._shopify_update_delivery_status(data)
                updated += 1
        return updated

    @api.model
    def cron_refresh_delivery_statuses(self):
        """Tâche planifiée : met à jour AUTOMATIQUEMENT le statut de
        livraison Shopify des commandes.

        Les changements du transporteur (En transit -> Livrée…) ne modifient
        pas toujours la date de mise à jour de la commande Shopify : l'import
        incrémental ne les voit donc pas. On relit ici les commandes dont la
        livraison n'est pas terminée (60 derniers jours).
        Au tout premier passage, toutes les anciennes commandes sont mises à
        jour une fois."""
        final_statuses = ("delivered", "picked_up", "failure")
        Order = self.env["sale.order"].sudo()
        for config in self.search([("state", "=", "connected"), ("sync_orders", "=", True)]):
            try:
                with self.env.cr.savepoint():
                    if not config.delivery_status_initialized:
                        config._shopify_refresh_delivery_statuses()
                        config.delivery_status_initialized = True
                    else:
                        orders = Order.search(
                            [
                                ("shopify_config_id", "=", config.id),
                                ("shopify_order_id", "!=", False),
                                ("state", "!=", "cancel"),
                                ("date_order", ">=", fields.Datetime.now() - timedelta(days=60)),
                                ("shopify_fulfillment_status", "!=", "restocked"),
                                "|",
                                ("shopify_delivery_status", "=", False),
                                ("shopify_delivery_status", "not in", final_statuses),
                            ]
                        )
                        if orders:
                            config._shopify_refresh_delivery_statuses(orders)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Mise à jour des statuts de livraison en erreur pour %s", config.name
                )
                self.env.cr.rollback()

    def action_shopify_confirm_quotations(self):
        """Bouton « Confirmer les devis Shopify » : transforme en commandes
        les commandes Shopify déjà importées qui sont restées en devis."""
        self.ensure_one()
        orders = self.env["sale.order"].sudo()._shopify_confirm_pending_quotations(
            self, limit=None
        )
        confirmed = len(orders.filtered(lambda o: o.state not in ("draft", "sent")))
        failed = len(orders) - confirmed
        message = f"{confirmed} devis Shopify traité(s) (confirmés ou annulés)."
        if failed:
            message += f" {failed} échec(s) : voir les journaux de synchronisation."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Commandes Shopify",
                "message": message,
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
            },
        }

    def action_sync_inventory_now(self):
        self.ensure_one()
        self.env["product.product"].sudo().shopify_import_inventory_levels(self)

    def action_push_inventory_now(self):
        """Bouton « Envoyer stock vers Shopify » : Odoo -> Shopify."""
        self.ensure_one()
        self.env["product.product"].sudo().shopify_push_inventory_all(self)

    def action_sync_all_now(self):
        """Bouton unique 'Tout importer maintenant' (produits, stock, clients,
        commandes) - équivalent à l'import complet manuel du connecteur
        officiel Shopify."""
        for config in self:
            config._run_full_import(incremental=False)

    # ------------------------------------------------------------------
    # Import automatique - se déclenche tout seul, sans action de
    # l'utilisateur, dans deux cas :
    #   1) juste après la connexion (première configuration)
    #   2) à intervalle régulier via le cron (filet de sécurité,
    #      indispensable quand les webhooks ne sont pas joignables : Odoo
    #      en local, réseau fermé, serveur de test, panne temporaire...)
    # ------------------------------------------------------------------
    def _run_initial_full_import(self):
        """Lance un import complet immédiatement après la connexion, pour que
        produits/clients/commandes/stock arrivent dans Odoo sans que
        l'utilisateur ait à cliquer sur les boutons manuels."""
        self.ensure_one()
        try:
            self._run_full_import(incremental=False)
            self.message_post(
                body=_(
                    "Import automatique initial terminé : produits, clients, "
                    "commandes et stock ont été synchronisés."
                )
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Erreur lors de l'import automatique initial Shopify")
            self.message_post(
                body=_(
                    "L'import automatique initial a rencontré une erreur : %s. "
                    "Vous pouvez relancer manuellement depuis les boutons "
                    "d'import, ou attendre la prochaine synchronisation "
                    "planifiée (toutes les 15 minutes)."
                )
                % exc
            )

    def _run_full_import(self, incremental=False):
        """Importe produits, stock, clients et commandes pour cette boutique,
        dans le bon ordre (produits avant commandes, car les commandes ont
        besoin des produits/variantes déjà importés).

        En tâche planifiée, chaque étape est ENREGISTRÉE séparément : avant,
        tout se faisait dans une seule transaction, et une étape lente ou en
        erreur (commandes, stock...) annulait aussi les modifications de
        produits déjà importées."""
        self.ensure_one()
        margin = timedelta(minutes=10)
        steps = []
        if self.sync_products and not incremental:
            # En automatique, les produits sont relus CHAQUE MINUTE par une
            # tâche dédiée (cron_sync_products_fast).
            since = None
            steps.append(("produits", lambda s=since: self.env["product.template"].sudo().shopify_import_all(self, updated_at_min=s)))
        if self.sync_customers:
            since = self.last_sync_customers - margin if incremental and self.last_sync_customers else None
            steps.append(("clients", lambda s=since: self.env["res.partner"].sudo().shopify_import_all(self, updated_at_min=s)))
        if self.sync_orders:
            since = self.last_sync_orders - margin if incremental and self.last_sync_orders else None
            steps.append(("commandes", lambda s=since: self.env["sale.order"].sudo().shopify_import_all(self, updated_at_min=s)))
        if self.sync_inventory:
            if incremental:
                # Odoo = référence du stock : on n'envoie que les écarts.
                steps.append(("stock", lambda: self.env["product.product"].sudo().shopify_push_inventory_all(self)))
            else:
                steps.append(("stock", lambda: self.env["product.product"].sudo().shopify_import_inventory_levels(self)))
        for label, step in steps:
            if not incremental:
                # Import complet : chaque étape est enregistrée dès qu'elle
                # est terminée (un worker tué en plein import ne perd plus
                # tout). Une erreur reste remontée (bouton manuel), mais la
                # transaction est restaurée proprement par le savepoint.
                with self.env.cr.savepoint():
                    step()
                self.env.cr.commit()
                continue
            try:
                with self.env.cr.savepoint():
                    step()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception("Synchronisation planifiée (%s) en erreur pour %s", label, self.name)
                self.env.cr.rollback()

    @api.model
    def cron_sync_products_fast(self):
        """Tâche « chaque minute » : applique dans Odoo les produits modifiés
        dans Shopify depuis le passage précédent (1 seul appel à Shopify
        quand rien n'a changé). Remplace les webhooks tant qu'Odoo n'est
        pas accessible en HTTPS."""
        for config in self.search([("state", "=", "connected"), ("sync_products", "=", True)]):
            # v9.7 : suppressions Shopify appliquées EN PREMIER. Sinon l'import
            # ci-dessous pouvait voir le produit « modifié » pendant sa
            # suppression et Odoo le renvoyait vers Shopify (cascade
            # d'erreurs « Product does not exist », 404, 422).
            try:
                self.env["product.template"].sudo()._shopify_archive_deleted_products(config)
                config.sudo().write({"shopify_deleted_checked_at": fields.Datetime.now()})
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception("Vérification des suppressions en erreur pour %s", config.name)
            since = (
                config.last_sync_products - timedelta(minutes=2)
                if config.last_sync_products
                else fields.Datetime.now() - timedelta(days=1)
            )
            try:
                with self.env.cr.savepoint():
                    self.env["product.template"].sudo().shopify_import_all(config, updated_at_min=since)
                self.env.cr.commit()
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Synchro produits (minute) en erreur pour %s", config.name)
                self.env.cr.rollback()
                try:
                    self.env["shopify.sync.log"].sudo().create({
                        "config_id": config.id, "direction": "in", "model_name": "product.template",
                        "shopify_object_type": "product", "state": "error",
                        "message": _("Synchro automatique des produits en échec (rien n'a été importé) : %s") % str(exc)[:500],
                    })
                    self.env.cr.commit()
                except Exception:  # noqa: BLE001
                    self.env.cr.rollback()
            try:
                with self.env.cr.savepoint():
                    self.env["product.template"].sudo().shopify_import_changed_variants(config, since)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception("Synchro variantes (minute) en erreur pour %s", config.name)
                self.env.cr.rollback()

    shopify_deleted_checked_at = fields.Datetime(
        string="Dernière vérification des suppressions", readonly=True, copy=False
    )

    # --- Santé de la boutique (couleurs liste / kanban, compteurs) ---
    SHOP_STATUS = [
        ("off", "Hors piste"),
        ("risk", "À risque"),
        ("ok", "Sur la bonne voie"),
        ("pause", "En pause"),
        ("done", "Terminé"),
    ]
    shop_status_manual = fields.Selection(
        SHOP_STATUS, string="Statut choisi", copy=False,
        help="Statut choisi à la main dans la liste. Vide = statut automatique.",
    )
    sync_health = fields.Selection(
        SHOP_STATUS,
        string="Statut", compute="_compute_sync_health", inverse="_inverse_sync_health",
        search="_search_sync_health",
        help="Choisi dans la liste (clic sur le badge), ou automatique :\n"
        "• Sur la bonne voie : connectée, aucune erreur depuis 7 jours.\n"
        "• À risque : quelques erreurs, ou notifications en attente.\n"
        "• Hors piste : non connectée, ou 100 erreurs et plus en 7 jours.\n"
        "« En pause » et « Terminé » se choisissent uniquement à la main.",
    )
    sync_health_is_auto = fields.Boolean(compute="_compute_sync_health", string="Statut automatique")
    sync_success_rate = fields.Integer(string="Réussite 7 j (%)", compute="_compute_sync_health")
    sync_error_label = fields.Char(string="Erreurs 7 j", compute="_compute_sync_health")

    def _shopify_health_of(self):
        """Statut affiché : celui choisi à la main, sinon l'automatique."""
        self.ensure_one()
        return self.shop_status_manual or self._shopify_auto_health()

    def _shopify_auto_health(self):
        self.ensure_one()
        if self.state != "connected" or self.sync_error_count >= 100:
            return "off"
        if self.sync_error_count or self.webhook_pending_count:
            return "risk"
        return "ok"

    def _compute_sync_health(self):
        since = fields.Datetime.now() - timedelta(days=7)
        groups = self.env["shopify.sync.log"].sudo()._read_group(
            [("config_id", "in", self.ids), ("create_date", ">=", since)],
            ["config_id", "state"], ["__count"],
        )
        counts = {}
        for config, state, count in groups:
            counts.setdefault(config.id, {})[state] = count
        for config in self:
            c = counts.get(config.id, {})
            total = c.get("success", 0) + c.get("error", 0)
            if config.state != "connected":
                config.sync_success_rate = 0
            else:
                config.sync_success_rate = round(100 * c.get("success", 0) / total) if total else 100
            config.sync_health = config._shopify_health_of()
            config.sync_health_is_auto = not config.shop_status_manual
            n = config.sync_error_count
            config.sync_error_label = "Aucune" if not n else f"{n} erreur{'s' if n > 1 else ''}"

    def _inverse_sync_health(self):
        for config in self:
            # Choisir la valeur automatique revient à repasser en automatique.
            auto = config._shopify_auto_health()
            value = config.sync_health
            config.shop_status_manual = False if (not value or value == auto) else value

    def action_shop_status_auto(self):
        """Repasse le statut en automatique (calculé)."""
        self.write({"shop_status_manual": False})

    def _search_sync_health(self, operator, value):
        values = value if isinstance(value, (list, tuple)) else [value]
        configs = self.with_context(active_test=False).search([])
        ids = [c.id for c in configs if c._shopify_health_of() in values]
        if operator in ("!=", "not in"):
            return [("id", "not in", ids)]
        return [("id", "in", ids)]

    @api.model
    def get_health_summary(self):
        """Compteurs pour la barre en haut de la page Boutiques."""
        configs = self.search([])
        result = {"ok": 0, "risk": 0, "off": 0, "pause": 0, "done": 0, "total": len(configs),
                  "products": 0, "orders": 0, "errors": 0}
        for config in configs:
            result[config._shopify_health_of()] += 1
            result["products"] += config.product_count
            result["orders"] += config.order_count
            result["errors"] += config.sync_error_count
        return result

    last_sync_products_ago = fields.Char(compute="_compute_sync_ago", string="Synchro produits")
    last_sync_orders_ago = fields.Char(compute="_compute_sync_ago", string="Synchro commandes")
    deleted_checked_ago = fields.Char(compute="_compute_sync_ago", string="Suppressions vérifiées")

    @staticmethod
    def _shopify_ago(dt, now):
        """Date -> « il y a 5 min » (lisible d'un coup d'œil)."""
        if not dt:
            return "jamais"
        sec = max(0, int((now - dt).total_seconds()))
        if sec < 60:
            return "à l'instant"
        if sec < 3600:
            return f"il y a {sec // 60} min"
        if sec < 86400:
            return f"il y a {sec // 3600} h"
        days = sec // 86400
        return f"il y a {days} jour{'s' if days > 1 else ''}"

    def _compute_sync_ago(self):
        now = fields.Datetime.now()
        for config in self:
            config.last_sync_products_ago = self._shopify_ago(config.last_sync_products, now)
            config.last_sync_orders_ago = self._shopify_ago(config.last_sync_orders, now)
            config.deleted_checked_ago = self._shopify_ago(config.shopify_deleted_checked_at, now)

    def _shopify_deletion_report(self):
        """Explication détaillée (en clair) de la suppression automatique
        pour cette boutique : vérification chaque minute + notifications
        instantanées (webhooks)."""
        self.ensure_one()
        now = fields.Datetime.now()
        lines = []

        def ago(dt):
            if not dt:
                return "jamais"
            sec = int((now - dt).total_seconds())
            if sec < 90:
                return f"il y a {sec} s"
            if sec < 5400:
                return f"il y a {sec // 60} min"
            return f"il y a {sec // 3600} h"

        # 1) Vérification chaque minute (tâche planifiée)
        cron = self.env.ref("shopify_odoo_connector.cron_shopify_products_fast", raise_if_not_found=False)
        lines.append("① VÉRIFICATION AUTOMATIQUE (chaque minute)")
        if not cron or not cron.active:
            lines.append("   ✗ Tâche « modifications produits Shopify -> Odoo (chaque minute) » DÉSACTIVÉE "
                         "(Paramètres > Technique > Actions planifiées).")
        else:
            lines.append(f"   Dernière vérification des suppressions : {ago(self.shopify_deleted_checked_at)}.")
            if not self.shopify_deleted_checked_at or (now - self.shopify_deleted_checked_at) > timedelta(minutes=5):
                lines.append("   ✗ Elle ne tourne pas : vérifiez que le serveur Odoo n'est pas lancé avec "
                             "max_cron_threads = 0 (odoo.conf) et redémarrez Odoo.")
            else:
                lines.append("   ✓ Elle tourne : un produit supprimé dans Shopify est traité en 1 à 2 minutes.")

        # 2) Notifications instantanées (webhooks)
        lines.append("② NOTIFICATION INSTANTANÉE (webhook Shopify)")
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        callback = f"{base_url}/shopify/webhook"
        lines.append(f"   Adresse d'Odoo donnée à Shopify : {callback}")
        if not base_url.startswith("https://"):
            lines.append("   ✗ Shopify n'envoie ses notifications qu'en HTTPS. Mettez l'adresse publique "
                         "https:// de votre serveur dans le paramètre système « web.base.url », puis "
                         "cliquez sur « Réinscrire les webhooks ».")
        elif any(h in base_url for h in ("localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.0.")):
            lines.append("   ✗ Cette adresse n'est pas joignable depuis Internet : Shopify ne peut pas l'appeler.")
        try:
            hooks = self.get_client().rest_get("/webhooks.json", params={"topic": "products/delete"}).get("webhooks", [])
            if not hooks:
                lines.append("   ✗ Webhook « products/delete » NON inscrit chez Shopify (cliquez sur « Réinscrire les webhooks »).")
            elif hooks[0].get("address") != callback:
                lines.append(f"   ✗ Shopify envoie vers une ancienne adresse : {hooks[0].get('address')} "
                             "(cliquez sur « Réinscrire les webhooks »).")
            else:
                lines.append("   ✓ Webhook « products/delete » inscrit chez Shopify à la bonne adresse.")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"   ? Impossible de lire les webhooks chez Shopify : {exc}")
        last_hook = self.env["shopify.webhook.log"].sudo().search(
            [("config_id", "=", self.id)], order="id desc", limit=1
        )
        last_delete = self.env["shopify.webhook.log"].sudo().search(
            [("config_id", "=", self.id), ("topic", "=", "products/delete")], order="id desc", limit=1
        )
        lines.append(f"   Dernière notification reçue de Shopify (tous types) : {ago(last_hook.create_date)}.")
        lines.append(f"   Dernière notification de suppression reçue : {ago(last_delete.create_date)}"
                     + (f" ({dict(last_delete._fields['state'].selection).get(last_delete.state)})." if last_delete else "."))
        if not last_hook or (now - last_hook.create_date) > timedelta(days=1):
            lines.append("   ✗ Aucune notification reçue depuis plus d'un jour : Shopify n'arrive pas à joindre Odoo. "
                         "Seule la vérification ① fonctionne (délai 1 à 2 min).")
        if not self.client_secret:
            lines.append("   ✗ « Client Secret » vide : Odoo refuse les notifications (signature invalide).")

        # 3) Réglages
        policy = dict(self._fields["product_delete_from_shopify"].selection).get(self.product_delete_from_shopify)
        lines.append("③ RÉGLAGES")
        lines.append(f"   Produit supprimé dans Shopify : {policy}. "
                     "Un produit utilisé dans des commandes / factures / stock est ARCHIVÉ (pas supprimé).")
        lines.append("   Produit supprimé dans Odoo → Shopify : "
                     + ("supprimé aussi dans Shopify." if self.product_delete_to_shopify else "rien (case décochée)."))
        return lines

    def action_check_deleted_now(self):
        """Bouton : vérifie tout de suite les produits supprimés dans
        Shopify, puis affiche un diagnostic détaillé."""
        self.ensure_one()
        total = self.env["product.template"].sudo()._shopify_archive_deleted_products(self) or 0
        self.sudo().write({"shopify_deleted_checked_at": fields.Datetime.now()})
        head = (
            f"{total} produit(s) supprimé(s) dans Shopify traité(s) maintenant (voir onglet Activité)."
            if total else "Aucun produit en attente de suppression : Odoo est à jour."
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Suppression automatique — diagnostic",
                "message": "\n".join([head, ""] + self._shopify_deletion_report()),
                "type": "success" if total else "info",
                "sticky": True,
                "className": "o_shopify_notif",
            },
        }

    @api.model
    def cron_sync_all_connected(self):
        """Appelée par la tâche planifiée (active par défaut) : synchronise
        toutes les boutiques connectées de façon incrémentale (uniquement ce
        qui a changé depuis la dernière synchro), afin de rester rapide même
        avec un intervalle court. Fait aussi respecter automatiquement les
        filtres de marque de chaque boutique directement sur Shopify (voir
        _shopify_enforce_brand_filter) : un produit d'une autre marque créé
        directement dans Shopify (admin, Point de vente, app tierce...) est
        donc archivé automatiquement, sans action manuelle."""
        configs = self.search([("state", "=", "connected")])
        # Rattrapage automatique : tout produit dont la marque correspond à
        # une boutique (CLERIEU, VONROS…) et qui n'y est pas encore est
        # envoyé sur cette boutique.
        try:
            with self.env.cr.savepoint():
                self.env["product.template"].sudo()._shopify_migrate_recompute_display()
            self.env.cr.commit()
        except Exception:  # noqa: BLE001
            _logger.exception("Envoi des produits vers la boutique de leur marque en erreur")
            self.env.cr.rollback()
        for config in configs:
            config._run_full_import(incremental=True)
            # Toute commande Shopify restée en devis est confirmée
            # automatiquement (commande Shopify = commande Odoo).
            try:
                with self.env.cr.savepoint():
                    self.env["sale.order"].sudo()._shopify_confirm_pending_quotations(config)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Confirmation automatique des devis Shopify en erreur pour %s", config.name
                )
                self.env.cr.rollback()
            if config.sync_products:
                try:
                    with self.env.cr.savepoint():
                        self.env["product.template"].sudo()._shopify_archive_deleted_products(config)
                    self.env.cr.commit()
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "Erreur lors du rattrapage des produits supprimés pour la boutique %s",
                        config.name,
                    )
            try:
                with self.env.cr.savepoint():
                    config._shopify_enforce_brand_filter()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Erreur lors de l'application automatique du filtre de "
                    "marque pour la boutique %s",
                    config.name,
                )

    def action_test_connection(self):
        self.ensure_one()
        client = self.get_client()
        try:
            shop_info = client.rest_get("/shop.json")
            self.message_post(
                body=_("Connexion réussie à la boutique : %s") % shop_info.get("shop", {}).get("name")
            )
        except ShopifyAPIError as exc:
            raise UserError(str(exc))


class ShopifyLocation(models.Model):
    _name = "shopify.location"
    _description = "Emplacement Shopify lié à un entrepôt Odoo"

    config_id = fields.Many2one("shopify.config", required=True, ondelete="cascade")
    shopify_location_id = fields.Char(required=True)
    name = fields.Char()
    warehouse_id = fields.Many2one("stock.warehouse", string="Entrepôt Odoo correspondant")

    _sql_constraints = [
        (
            "loc_uniq",
            "unique(config_id, shopify_location_id)",
            "Cet emplacement Shopify est déjà mappé.",
        ),
    ]
