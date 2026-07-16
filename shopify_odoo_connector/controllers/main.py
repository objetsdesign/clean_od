# -*- coding: utf-8 -*-
import json
import logging
import time

from odoo import http
from odoo.http import request

from ..models.shopify_api_client import ShopifyAPIClient

_logger = logging.getLogger(__name__)


class ShopifyConnectorController(http.Controller):

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
            template = (
                ctx_env["product.template"]
                .sudo()
                .search(
                    [
                        ("shopify_product_id", "=", str(payload.get("id"))),
                        ("shopify_config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if template:
                template.write({"active": False, "sale_ok": False})

        elif topic in ("customers/create", "customers/update"):
            ctx_env["res.partner"].sudo()._shopify_create_or_update_from_data(payload, config)

        elif topic == "customers/delete":
            partner = (
                ctx_env["res.partner"]
                .sudo()
                .search(
                    [
                        ("shopify_customer_id", "=", str(payload.get("id"))),
                        ("shopify_config_id", "=", config.id),
                    ],
                    limit=1,
                )
            )
            if partner:
                partner.write({"active": False})

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

        variant = (
            env["product.product"]
            .sudo()
            .search(
                [
                    ("shopify_inventory_item_id", "=", inventory_item_id),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
        )
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
