# -*- coding: utf-8 -*-
"""Client bas niveau pour l'API Etsy Open API v3.

Contrairement à Shopify, Etsy exige :
- une authentification OAuth 2.0 AVEC PKCE (code_verifier / code_challenge) :
  il n'existe pas d'équivalent au "token d'accès direct" de Shopify ;
- un header `x-api-key` (le Keystring/Client ID de l'app développeur Etsy)
  EN PLUS du Bearer token, sur CHAQUE appel ;
- un access_token qui expire (1h) et se renouvelle via un refresh_token.

Documentation officielle : https://developers.etsy.com/documentation/
"""
import base64
import hashlib
import logging
import secrets
import time

import requests

_logger = logging.getLogger(__name__)

API_BASE = "https://openapi.etsy.com/v3/application"
AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
MAX_RETRIES = 5


class EtsyAPIError(Exception):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class EtsyAPIClient:
    def __init__(self, client_id, access_token, timeout=30):
        self.client_id = client_id
        self.access_token = access_token
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Requête bas niveau
    # ------------------------------------------------------------------
    def _headers(self):
        return {
            "x-api-key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
        }

    def _request(self, method, path, params=None, json_payload=None, files=None, data=None):
        url = f"{API_BASE}{path}"
        retries = 0
        while True:
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_payload if files is None else None,
                    data=data if files is not None else None,
                    files=files,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                raise EtsyAPIError(f"Erreur réseau vers Etsy : {exc}") from exc

            if response.status_code == 429 and retries < MAX_RETRIES:
                retry_after = float(response.headers.get("Retry-After", 2))
                _logger.warning("Etsy rate limit atteint, nouvelle tentative dans %.2fs", retry_after)
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code >= 400:
                raise EtsyAPIError(
                    f"Etsy API error {response.status_code} sur {method} {path} : {response.text}",
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

    def get(self, path, params=None):
        return self._safe_json(self._request("GET", path, params=params))

    def post(self, path, payload):
        return self._safe_json(self._request("POST", path, json_payload=payload))

    def patch(self, path, payload):
        return self._safe_json(self._request("PATCH", path, json_payload=payload))

    def put(self, path, payload):
        return self._safe_json(self._request("PUT", path, json_payload=payload))

    def delete(self, path):
        return self._safe_json(self._request("DELETE", path))

    def post_file(self, path, field_name, filename, file_bytes, extra_data=None):
        files = {field_name: (filename, file_bytes)}
        return self._safe_json(
            self._request("POST", path, files=files, data=extra_data or {})
        )

    # ------------------------------------------------------------------
    # Endpoints "listings" (annonces)
    # ------------------------------------------------------------------
    def create_draft_listing(self, shop_id, payload):
        return self.post(f"/shops/{shop_id}/listings", payload)

    def update_listing(self, shop_id, listing_id, payload):
        return self.patch(f"/shops/{shop_id}/listings/{listing_id}", payload)

    def get_listing(self, listing_id):
        return self.get(f"/listings/{listing_id}")

    def update_listing_inventory(self, listing_id, payload):
        return self.put(f"/listings/{listing_id}/inventory", payload)

    def upload_listing_image(self, shop_id, listing_id, image_bytes, filename="image.jpg", rank=None):
        extra = {}
        if rank is not None:
            extra["rank"] = str(rank)
        return self.post_file(
            f"/shops/{shop_id}/listings/{listing_id}/images", "image", filename, image_bytes, extra
        )

    def delete_listing(self, listing_id):
        return self.delete(f"/listings/{listing_id}")

    # ------------------------------------------------------------------
    # Aides à la configuration (l'utilisateur en a besoin une fois)
    # ------------------------------------------------------------------
    def get_shop(self, shop_id):
        return self.get(f"/shops/{shop_id}")

    def get_shipping_profiles(self, shop_id):
        return self.get(f"/shops/{shop_id}/shipping-profiles")

    def get_seller_taxonomy(self):
        return self.get("/seller-taxonomy/nodes")

    # ------------------------------------------------------------------
    # OAuth 2.0 + PKCE
    # ------------------------------------------------------------------
    @staticmethod
    def generate_pkce_pair():
        """Retourne (code_verifier, code_challenge) pour le flux PKCE
        obligatoire chez Etsy (pas de "client secret" côté échange final,
        contrairement à Shopify)."""
        code_verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    @staticmethod
    def build_authorize_url(client_id, redirect_uri, scope, state, code_challenge):
        from urllib.parse import urlencode

        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    @staticmethod
    def exchange_code_for_token(client_id, redirect_uri, code, code_verifier):
        response = requests.post(
            TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise EtsyAPIError(
                f"Échec de l'échange du code OAuth Etsy : {response.text}",
                status_code=response.status_code,
            )
        return response.json()

    @staticmethod
    def refresh_access_token(client_id, refresh_token):
        response = requests.post(
            TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise EtsyAPIError(
                f"Échec du rafraîchissement du token Etsy : {response.text}",
                status_code=response.status_code,
            )
        return response.json()
