# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import logging
import time

import requests

_logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-10"
MAX_RETRIES = 5


class ShopifyAPIError(Exception):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ShopifyAPIClient:
    """Client bas niveau pour l'API Admin de Shopify (REST + GraphQL).

    Gère automatiquement :
    - l'authentification par Bearer token (OAuth) / X-Shopify-Access-Token
    - le rate limiting (leaky bucket) avec retry automatique
    - les erreurs HTTP avec informations exploitables
    """

    def __init__(self, shop_url, access_token, api_version=None, timeout=30):
        # shop_url attendu sous la forme "monshop.myshopify.com"
        self.shop_url = shop_url.replace("https://", "").replace("http://", "").strip("/")
        self.access_token = access_token
        self.api_version = api_version or DEFAULT_API_VERSION
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Helpers bas niveau
    # ------------------------------------------------------------------
    @property
    def base_url(self):
        return f"https://{self.shop_url}/admin/api/{self.api_version}"

    def _headers(self):
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, params=None, json_payload=None):
        url = f"{self.base_url}{path}"
        retries = 0
        while True:
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_payload,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                raise ShopifyAPIError(f"Erreur réseau vers Shopify : {exc}") from exc

            if response.status_code == 429 and retries < MAX_RETRIES:
                retry_after = float(response.headers.get("Retry-After", 1))
                _logger.warning(
                    "Shopify rate limit atteint, nouvelle tentative dans %.2fs", retry_after
                )
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code >= 400:
                raise ShopifyAPIError(
                    f"Shopify API error {response.status_code} sur {method} {path} : {response.text}",
                    status_code=response.status_code,
                    payload=self._safe_json(response),
                )

            return response

    @staticmethod
    def _safe_json(response):
        try:
            return response.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------
    def rest_get(self, path, params=None):
        return self._safe_json(self._request("GET", path, params=params))

    def rest_get_with_pagination(self, path, params=None, limit_pages=50):
        """Suit les liens 'next' du header Link pour paginer automatiquement."""
        results = []
        next_params = dict(params or {})
        next_path = path
        pages = 0
        while next_path and pages < limit_pages:
            response = self._request("GET", next_path, params=next_params)
            data = self._safe_json(response)
            key = next(iter(data.keys())) if data else None
            if key:
                results.extend(data[key])
            next_path, next_params = self._extract_next_link(response)
            pages += 1
        return results

    @staticmethod
    def _extract_next_link(response):
        link_header = response.headers.get("Link", "")
        if not link_header:
            return None, None
        parts = link_header.split(",")
        for part in parts:
            if 'rel="next"' in part:
                url = part.split(";")[0].strip("<> ")
                # on transforme l'URL complète en path + params relatifs
                from urllib.parse import urlparse, parse_qs

                parsed = urlparse(url)
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                return "/" + parsed.path.split("/admin/api/")[-1].split("/", 1)[-1], query
        return None, None

    def rest_post(self, path, payload):
        return self._safe_json(self._request("POST", path, json_payload=payload))

    def rest_put(self, path, payload):
        return self._safe_json(self._request("PUT", path, json_payload=payload))

    def rest_delete(self, path):
        return self._safe_json(self._request("DELETE", path))

    # ------------------------------------------------------------------
    # GraphQL
    # ------------------------------------------------------------------
    def graphql(self, query, variables=None):
        payload = {"query": query, "variables": variables or {}}
        response = self._request("POST", "/graphql.json", json_payload=payload)
        data = self._safe_json(response)
        if "errors" in data:
            raise ShopifyAPIError(f"Erreur GraphQL Shopify : {data['errors']}", payload=data)
        return data.get("data", {})

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    @staticmethod
    def build_authorize_url(shop_url, client_id, redirect_uri, scope, state):
        shop_url = shop_url.replace("https://", "").replace("http://", "").strip("/")
        return (
            f"https://{shop_url}/admin/oauth/authorize"
            f"?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}&state={state}"
        )

    @staticmethod
    def exchange_code_for_token(shop_url, client_id, client_secret, code):
        shop_url = shop_url.replace("https://", "").replace("http://", "").strip("/")
        url = f"https://{shop_url}/admin/oauth/access_token"
        response = requests.post(
            url,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise ShopifyAPIError(
                f"Échec de l'échange du code OAuth Shopify : {response.text}",
                status_code=response.status_code,
            )
        return response.json()

    # ------------------------------------------------------------------
    # Sécurité Webhooks / OAuth
    # ------------------------------------------------------------------
    @staticmethod
    def verify_hmac(data, hmac_header, secret):
        """Vérifie la signature HMAC-SHA256 d'un webhook Shopify."""
        if not hmac_header or not secret:
            return False
        digest = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
        computed_hmac = base64.b64encode(digest).decode()
        return hmac.compare_digest(computed_hmac, hmac_header)

    @staticmethod
    def verify_oauth_hmac(params, secret):
        """Vérifie le paramètre hmac renvoyé lors du callback OAuth."""
        params = dict(params)
        received_hmac = params.pop("hmac", None)
        if not received_hmac:
            return False
        message = "&".join(
            f"{key}={value}" for key, value in sorted(params.items())
        )
        digest = hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(digest, received_hmac)
