# -*- coding: utf-8 -*-
import json
import logging
import time

from odoo import http
from odoo.http import request

from ..models.shopify_api_client import ShopifyAPIClient
from ..models.etsy_api_client import EtsyAPIError, etsy_request_token

_logger = logging.getLogger(__name__)


class ShopifyConnectorController(http.Controller):

    # ------------------------------------------------------------------
    # Dashboard - statistiques de vente (courbes / KPI)
    # ------------------------------------------------------------------
    @http.route("/shopify_connector/dashboard_data", type="json", auth="user")
    def shopify_dashboard_data(self, date_from, date_to, config_id=None, granularity=None):
        if not request.env.user.has_group("shopify_odoo_connector.group_shopify_user"):
            return {"error": "Accès non autorisé."}
        try:
            return (
                request.env["shopify.dashboard"]
                .sudo()
                .get_dashboard_data(date_from, date_to, config_id=config_id, granularity=granularity)
            )
        except Exception:
            # On ne laisse JAMAIS une exception remonter brute ici : côté JS,
            # rpc() ne recevrait pas un JSON-RPC valide et tomberait dans le
            # catch générique ("Impossible de charger les statistiques."),
            # ce qui masque complètement la vraie cause. On logge le
            # traceback complet côté serveur et on renvoie un message
            # exploitable (avec le détail technique si le mode développeur
            # est actif) pour que l'erreur réelle soit toujours visible.
            _logger.exception("Erreur lors du calcul des statistiques du dashboard Shopify")
            message = "Erreur lors du calcul des statistiques."
            if request.env.user.has_group("base.group_no_one"):
                import traceback

                message = f"{message}\n{traceback.format_exc()}"
            return {"error": message}

    # ------------------------------------------------------------------
    # OAuth ETSY (mode "API Etsy") - retour après autorisation du vendeur
    # ------------------------------------------------------------------
    @http.route("/shopify/etsy/oauth/callback", type="http", auth="user", csrf=False)
    def shopify_etsy_oauth_callback(self, code=None, state=None, error=None, error_description=None, **kwargs):
        if not request.env.user.has_group("shopify_odoo_connector.group_shopify_manager"):
            return request.make_response("Accès non autorisé.", status=403)
        if error:
            return request.make_response(f"Etsy a refusé l'accès : {error_description or error}", status=400)
        Marketplace = request.env["shopify.marketplace"].sudo()
        account = Marketplace.search([("etsy_oauth_state", "=", state)], limit=1) if state else Marketplace
        if not account or not code:
            return request.make_response("Requête Etsy invalide (state inconnu).", status=400)
        try:
            token = etsy_request_token(
                {
                    "grant_type": "authorization_code",
                    "client_id": account.etsy_keystring,
                    "redirect_uri": account.etsy_redirect_uri,
                    "code": code,
                    "code_verifier": account.etsy_code_verifier,
                }
            )
            account._etsy_store_token(token)
            # Le jeton est préfixé par le user_id Etsy ; getMe donne le shop_id.
            me = account._etsy_client().get_me()
            account.write(
                {
                    "etsy_shop_id": str(me.get("shop_id") or ""),
                    "etsy_connected": bool(me.get("shop_id")),
                    "etsy_oauth_state": False,
                    "etsy_code_verifier": False,
                }
            )
        except EtsyAPIError as exc:
            _logger.exception("Échec de la connexion OAuth Etsy")
            return request.make_response(f"Connexion Etsy impossible : {exc}", status=400)
        return request.redirect(
            f"/web#id={account.id}&model=shopify.marketplace&view_type=form"
        )

    # ------------------------------------------------------------------
    # OAuth - installation & callback
    # ------------------------------------------------------------------
    @http.route("/shopify/install", type="http", auth="user", website=False, csrf=False)
    def shopify_install(self, shop=None, **kwargs):
        """Point d'entrée optionnel pour démarrer l'installation depuis Shopify
        (App Store) en identifiant automatiquement la config existante."""
        Config = request.env["shopify.config"].sudo()
        config = Config.search([("shop_url", "=", shop)], limit=1)
        if not config:
            return request.make_response(
                "Aucune configuration Shopify trouvée pour ce domaine. "
                "Créez d'abord un enregistrement shopify.config dans Odoo.",
                status=404,
            )
        action = config.action_connect_oauth()
        return request.redirect(action["url"])

    @http.route("/shopify/oauth/callback", type="http", auth="public", website=False, csrf=False)
    def shopify_oauth_callback(self, **kwargs):
        shop = kwargs.get("shop")
        code = kwargs.get("code")
        state = kwargs.get("state")

        Config = request.env["shopify.config"].sudo()
        config = Config.search([("shop_url", "=", shop)], limit=1)
        if not config:
            return request.make_response("Boutique Shopify inconnue.", status=404)

        if not ShopifyAPIClient.verify_oauth_hmac(kwargs, config.client_secret):
            return request.make_response("Signature HMAC OAuth invalide.", status=401)

        if state and config.oauth_state and state != config.oauth_state:
            return request.make_response("État OAuth invalide (CSRF).", status=401)

        try:
            config._oauth_complete(code)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Erreur lors de la finalisation OAuth Shopify")
            config.write({"state": "error", "last_error": str(exc)})
            return request.make_response(f"Erreur OAuth : {exc}", status=500)

        return request.make_response(
            "<h3>Connexion Shopify réussie ! Vous pouvez fermer cette fenêtre.</h3>",
            headers=[("Content-Type", "text/html")],
        )

    # ------------------------------------------------------------------
    # Webhooks - réception en temps réel
    # ------------------------------------------------------------------
    @http.route("/shopify/webhook", type="http", auth="public", methods=["POST"], csrf=False)
    def shopify_webhook(self, **kwargs):
        start = time.time()
        raw_body = request.httprequest.data
        headers = request.httprequest.headers

        topic = headers.get("X-Shopify-Topic", "")
        shop_domain = headers.get("X-Shopify-Shop-Domain", "")
        hmac_header = headers.get("X-Shopify-Hmac-Sha256", "")

        Config = request.env["shopify.config"].sudo()
        config = Config.search([("shop_url", "=", shop_domain)], limit=1)
        if not config:
            _logger.warning("Webhook Shopify reçu pour une boutique inconnue : %s", shop_domain)
            return request.make_response("Boutique inconnue", status=404)

        if not ShopifyAPIClient.verify_hmac(raw_body, hmac_header, config.client_secret):
            _logger.warning("Webhook Shopify : signature HMAC invalide (%s)", topic)
            return request.make_response("Signature invalide", status=401)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except ValueError:
            payload = {}

        log = request.env["shopify.webhook.log"].sudo().create(
            {
                "config_id": config.id,
                "topic": topic,
                "shop_domain": shop_domain,
                "payload": json.dumps(payload, indent=2),
                "state": "received",
            }
        )

        try:
            self._dispatch_webhook(config, topic, payload)
            log.write(
                {"state": "processed", "processing_time": time.time() - start}
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Erreur de traitement du webhook Shopify %s", topic)
            log.write(
                {
                    "state": "error",
                    "error_message": str(exc),
                    "processing_time": time.time() - start,
                }
            )
            # On répond 200 quand même pour éviter que Shopify désactive le
            # webhook après trop d'échecs successifs ; l'erreur reste tracée.

        return request.make_response("ok", status=200)

    def _dispatch_webhook(self, config, topic, payload):
        env = request.env
        ctx_env = env(context=dict(env.context, shopify_sync=True))

        if topic in ("products/create", "products/update"):
            ctx_env["product.template"].sudo()._shopify_create_or_update_from_data(
                payload, config
            )

        elif topic == "products/delete":
            # Produit dédié marketplace supprimé à la main dans Shopify :
            # on oublie le lien, il sera recréé au prochain envoi.
            mp_links = (
                ctx_env["shopify.marketplace.product.link"]
                .sudo()
                .search(
                    [
                        ("shopify_product_id", "=", str(payload.get("id"))),
                        ("config_id", "=", config.id),
                    ]
                )
            )
            if mp_links:
                ctx_env["shopify.marketplace.variant.link"].sudo().search(
                    [
                        ("config_id", "=", config.id),
                        ("marketplace_id", "in", mp_links.marketplace_id.ids),
                        ("product_id", "in", mp_links.product_tmpl_id.product_variant_ids.ids),
                    ]
                ).unlink()
                mp_links.unlink()
                return
            link = (
                ctx_env["shopify.product.link"]
                .sudo()
                .search(
                    [
                        ("shopify_product_id", "=", str(payload.get("id"))),
                        ("config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if link:
                link.write({"active": False})
                # On ne désactive le produit Odoo lui-même que s'il n'est
                # plus lié à AUCUNE autre boutique (catalogue partagé).
                remaining_links = link.product_tmpl_id.shopify_link_ids.filtered("active")
                if not remaining_links:
                    link.product_tmpl_id.write({"active": False, "sale_ok": False})

        elif topic in ("customers/create", "customers/update"):
            ctx_env["res.partner"].sudo()._shopify_create_or_update_from_data(payload, config)

        elif topic == "customers/delete":
            link = (
                ctx_env["shopify.partner.link"]
                .sudo()
                .search(
                    [
                        ("shopify_customer_id", "=", str(payload.get("id"))),
                        ("config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if link:
                link.write({"active": False})
                remaining_links = link.partner_id.shopify_partner_link_ids.filtered("active")
                if not remaining_links:
                    link.partner_id.write({"active": False})

        elif topic in ("orders/create", "orders/updated", "orders/paid"):
            ctx_env["sale.order"].sudo()._shopify_create_or_update_from_data(payload, config)

        elif topic == "orders/cancelled":
            order = (
                ctx_env["sale.order"]
                .sudo()
                .search(
                    [
                        ("shopify_order_id", "=", str(payload.get("id"))),
                        ("shopify_config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if order and order.state not in ("cancel", "done"):
                order.action_cancel()

        elif topic in ("fulfillments/create", "fulfillments/update", "orders/fulfilled"):
            order_id = payload.get("order_id") or payload.get("id")
            order = (
                ctx_env["sale.order"]
                .sudo()
                .search(
                    [
                        ("shopify_order_id", "=", str(order_id)),
                        ("shopify_config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if order:
                order.write(
                    {
                        "shopify_fulfillment_status": payload.get("status")
                        or payload.get("fulfillment_status")
                        or "fulfilled"
                    }
                )

        elif topic == "inventory_levels/update":
            self._handle_inventory_level_update(config, payload)

        elif topic == "app/uninstalled":
            config.write({"state": "draft", "access_token": False})

        else:
            _logger.info("Topic webhook Shopify non géré : %s", topic)

    @staticmethod
    def _handle_inventory_level_update(config, payload):
        env = request.env
        inventory_item_id = str(payload.get("inventory_item_id"))
        location_id = str(payload.get("location_id"))
        available = payload.get("available")

        variant_link = (
            env["shopify.variant.link"]
            .sudo()
            .search(
                [
                    ("shopify_inventory_item_id", "=", inventory_item_id),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
        )
        variant = variant_link.product_id
        location = (
            env["shopify.location"]
            .sudo()
            .search(
                [
                    ("shopify_location_id", "=", location_id),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
        )
        if not variant or not location or not location.warehouse_id or available is None:
            return

        quant = (
            env["stock.quant"]
            .sudo()
            .search(
                [
                    ("product_id", "=", variant.id),
                    ("location_id", "=", location.warehouse_id.lot_stock_id.id),
                ],
                limit=1,
            )
        )
        if quant:
            quant.with_context(shopify_sync=True).write({"inventory_quantity": available})
        else:
            env["stock.quant"].sudo().with_context(shopify_sync=True)._update_available_quantity(
                variant, location.warehouse_id.lot_stock_id, available
            )
