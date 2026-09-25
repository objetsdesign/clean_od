# -*- coding: utf-8 -*-
import hashlib
import json
import logging

import requests
import secrets
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .shopify_api_client import ShopifyAPIClient, ShopifyAPIError, DEFAULT_API_VERSION

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sanitize_auth_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        # Un copier-coller depuis l'interface Shopify (bouton "Reveal"/
        # "Afficher") ajoute très souvent un espace ou un retour à la
        # ligne invisible en fin de valeur. Un seul caractère en trop
        # dans le Client Secret suffit à faire échouer la vérification
        # HMAC OAuth ("Signature HMAC OAuth invalide") sans qu'aucune
        # erreur ne soit visible en relisant le champ. On nettoie donc
        # systématiquement ces champs avant de les stocker.
        self._sanitize_auth_vals(vals)
        return super().write(vals)

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
        string="N'exporter QUE ces marques",
        default="Clérieu",
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
            ("gtin", "GTIN / EAN", "single_line_text_field"),
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

    def _schedule_post_oauth_setup(self):
        """Planifie (cron ponctuel, exécuté dans la minute) l'enregistrement
        des webhooks, la synchro des emplacements et l'import initial complet,
        pour que le contrôleur OAuth puisse répondre immédiatement au
        navigateur sans risquer un timeout proxy (voir _oauth_complete).

        NB : depuis Odoo 18, `ir.cron` n'a plus de champ `numbercall`/`doall`
        (un cron actif se ré-exécute indéfiniment selon son intervalle). Pour
        un job ponctuel, on désactive donc nous-mêmes le cron à la fin de son
        exécution (voir _run_post_oauth_setup), plutôt que de s'appuyer sur
        numbercall=1 comme sur les anciennes versions."""
        self.ensure_one()
        Cron = self.env["ir.cron"].sudo()
        cron = Cron.create(
            {
                "name": f"Shopify : finalisation connexion ({self.name})",
                "model_id": self.env["ir.model"]._get_id(self._name),
                "state": "code",
                "code": "pass",
                "interval_number": 1,
                "interval_type": "minutes",
                "nextcall": fields.Datetime.now(),
                "active": True,
            }
        )
        cron.code = f"model.browse({self.id})._run_post_oauth_setup(cron_id={cron.id})"

    def _run_post_oauth_setup(self, cron_id=None):
        """Exécutée en tâche de fond après une connexion OAuth réussie :
        webhooks, emplacements, import initial complet. Se désactive
        elle-même à la fin (voir _schedule_post_oauth_setup) pour ne
        s'exécuter qu'une seule fois."""
        self.ensure_one()
        try:
            self._register_webhooks()
            self._sync_locations()
            self.message_post(body=_("Connexion OAuth Shopify réussie."))
            self._run_initial_full_import()
        finally:
            if cron_id:
                self.env["ir.cron"].sudo().browse(cron_id).active = False

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
    def _sync_locations(self):
        self.ensure_one()
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
        self.ensure_one()
        self.env["product.template"].sudo().shopify_import_all(self)

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
        besoin des produits/variantes déjà importés)."""
        self.ensure_one()
        # Petite marge de sécurité (10 min) pour ne rien perdre en cas de
        # léger décalage entre deux exécutions du cron.
        margin = timedelta(minutes=10)

        if self.sync_products:
            since = self.last_sync_products - margin if incremental and self.last_sync_products else None
            self.env["product.template"].sudo().shopify_import_all(self, updated_at_min=since)
        if self.sync_customers:
            since = self.last_sync_customers - margin if incremental and self.last_sync_customers else None
            self.env["res.partner"].sudo().shopify_import_all(self, updated_at_min=since)
        if self.sync_orders:
            since = self.last_sync_orders - margin if incremental and self.last_sync_orders else None
            self.env["sale.order"].sudo().shopify_import_all(self, updated_at_min=since)
        if self.sync_inventory:
            if incremental:
                # Tâche planifiée : Odoo est la RÉFÉRENCE du stock. On envoie
                # le stock Odoo vers Shopify au lieu de réimporter celui de
                # Shopify, qui écrasait le stock Odoo toutes les 15 min (et
                # décomptait deux fois les ventes Shopify : une fois via
                # l'import, une fois via la livraison Odoo).
                self.env["product.product"].sudo().shopify_push_inventory_all(self)
            else:
                self.env["product.product"].sudo().shopify_import_inventory_levels(self)

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
        for config in configs:
            try:
                with self.env.cr.savepoint():
                    config._run_full_import(incremental=True)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Erreur lors de la synchronisation planifiée de la boutique %s",
                    config.name,
                )
            if config.sync_products:
                try:
                    with self.env.cr.savepoint():
                        self.env["product.template"].sudo()._shopify_archive_deleted_products(config)
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
