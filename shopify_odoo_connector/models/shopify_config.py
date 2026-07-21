# -*- coding: utf-8 -*-
import logging
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
    "read_shipping,write_shipping"
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

    state = fields.Selection(
        [("draft", "Brouillon"), ("connected", "Connectée"), ("error", "Erreur")],
        default="draft",
        tracking=True,
    )
    last_error = fields.Text(readonly=True)

    # --- Synchronisation ---
    sync_products = fields.Boolean(default=True)
    sync_inventory = fields.Boolean(default=True)
    sync_customers = fields.Boolean(default=True)
    sync_orders = fields.Boolean(default=True)
    sync_payments = fields.Boolean(default=True)
    sync_fulfillments = fields.Boolean(default=True)
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
    order_count = fields.Integer(compute="_compute_dashboard_counts", string="Commandes")
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
                [("shopify_config_id", "=", config.id)]
            )
            config.customer_count = Partner.search_count(
                [("shopify_config_id", "=", config.id)]
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
        action["domain"] = [("shopify_config_id", "=", self.id)]
        return action

    def action_view_shopify_customers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Clients Shopify",
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("shopify_config_id", "=", self.id)],
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
        """Appelée par le contrôleur après réception du 'code' OAuth."""
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
        self._register_webhooks()
        self._sync_locations()
        self.message_post(body=_("Connexion OAuth Shopify réussie."))
        self._run_initial_full_import()

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

    def action_resync_webhooks(self):
        for config in self:
            config._register_webhooks()

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
    def action_sync_products_now(self):
        self.ensure_one()
        self.env["product.template"].sudo().shopify_import_all(self)

    def action_sync_customers_now(self):
        self.ensure_one()
        self.env["res.partner"].sudo().shopify_import_all(self)

    def action_sync_orders_now(self):
        self.ensure_one()
        self.env["sale.order"].sudo().shopify_import_all(self)

    def action_sync_inventory_now(self):
        self.ensure_one()
        self.env["product.product"].sudo().shopify_import_inventory_levels(self)

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
            self.env["product.product"].sudo().shopify_import_inventory_levels(self)

    @api.model
    def cron_sync_all_connected(self):
        """Appelée par la tâche planifiée (active par défaut) : synchronise
        toutes les boutiques connectées de façon incrémentale (uniquement ce
        qui a changé depuis la dernière synchro), afin de rester rapide même
        avec un intervalle court."""
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
