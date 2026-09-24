# -*- coding: utf-8 -*-
"""Client minimal pour l'API officielle Etsy (Open API v3).

Sert UNIQUEMENT à mettre à jour le contenu propre à Etsy (titre,
description, tags, matériaux, prix) d'une annonce Etsy qui existe déjà,
directement depuis Odoo. Le produit Shopify reste UNIQUE (contenu Amazon) ;
OrderBridge continue de gérer commandes, suivi et stock.

Rappels API Etsy :
* en-tête `x-api-key` = "keystring:shared_secret" (obligatoire depuis
  février 2026) ;
* OAuth 2.0 avec PKCE, jeton d'accès valable 1 h, jeton de
  rafraîchissement valable 90 jours ;
* `updateListing` : PATCH /shops/{shop_id}/listings/{listing_id}
  (form-urlencoded) ;
* `getListingInventory` / `updateListingInventory` :
  GET / PUT /listings/{listing_id}/inventory (JSON, inventaire COMPLET).
"""
import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import requests

_logger = logging.getLogger(__name__)

ETSY_API_BASE = "https://api.etsy.com/v3/application"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
ETSY_CONNECT_URL = "https://www.etsy.com/oauth/connect"
ETSY_SCOPES = "listings_r listings_w shops_r"
MAX_RETRIES = 4


class EtsyAPIError(Exception):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def etsy_pkce_pair():
    """Retourne (code_verifier, code_challenge) conformes à la RFC 7636."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def etsy_authorize_url(keystring, redirect_uri, state, code_challenge):
    params = {
        "response_type": "code",
        "client_id": keystring,
        "redirect_uri": redirect_uri,
        "scope": ETSY_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{ETSY_CONNECT_URL}?{urlencode(params)}"


def etsy_request_token(data, timeout=30):
    """POST sur l'endpoint OAuth Etsy (code -> jeton, ou rafraîchissement)."""
    response = requests.post(ETSY_TOKEN_URL, data=data, timeout=timeout)
    if response.status_code >= 400:
        raise EtsyAPIError(
            f"Etsy OAuth {response.status_code} : {response.text[:500]}",
            status_code=response.status_code,
            payload=response.text,
        )
    return response.json()


class EtsyAPIClient:
    """`account` est l'enregistrement shopify.marketplace (type Etsy) qui
    porte les identifiants. Le jeton est rafraîchi automatiquement."""

    def __init__(self, account, timeout=30):
        self.account = account
        self.timeout = timeout

    # ------------------------------------------------------------------
    def _api_key(self):
        acc = self.account
        if not acc.etsy_keystring or not acc.etsy_shared_secret:
            raise EtsyAPIError(
                "Keystring / Shared secret Etsy manquants (fiche marketplace Etsy)."
            )
        return f"{acc.etsy_keystring}:{acc.etsy_shared_secret}"

    def _access_token(self):
        acc = self.account
        if not acc.etsy_refresh_token:
            raise EtsyAPIError(
                "Etsy n'est pas connecté : cliquez sur « Connecter Etsy » "
                "dans la fiche marketplace Etsy."
            )
        # Marge de 2 minutes avant expiration.
        if acc.etsy_access_token and (acc.etsy_token_expires_at or 0) > time.time() + 120:
            return acc.etsy_access_token
        token = etsy_request_token(
            {
                "grant_type": "refresh_token",
                "client_id": acc.etsy_keystring,
                "refresh_token": acc.etsy_refresh_token,
            },
            timeout=self.timeout,
        )
        acc._etsy_store_token(token)
        return token["access_token"]

    def _request(self, method, path, form=None, json_payload=None, params=None):
        url = f"{ETSY_API_BASE}{path}"
        retries = 0
        while True:
            headers = {
                "x-api-key": self._api_key(),
                "Authorization": f"Bearer {self._access_token()}",
            }
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    data=form,
                    json=json_payload,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise EtsyAPIError(f"Erreur réseau Etsy : {exc}") from exc
            if response.status_code == 429 and retries < MAX_RETRIES:
                retries += 1
                time.sleep(float(response.headers.get("Retry-After", 2 * retries)))
                continue
            if response.status_code == 401 and retries == 0:
                # Jeton révoqué/expiré avant l'heure : on force un refresh.
                retries += 1
                self.account.sudo().write({"etsy_token_expires_at": 0})
                continue
            if response.status_code >= 400:
                raise EtsyAPIError(
                    f"Etsy {method} {path} -> {response.status_code} : {response.text[:800]}",
                    status_code=response.status_code,
                    payload=response.text,
                )
            if not response.content:
                return {}
            return response.json()

    # ------------------------------------------------------------------
    # Endpoints utilisés
    # ------------------------------------------------------------------
    def get_me(self):
        """getMe : renvoie user_id et shop_id du vendeur connecté."""
        return self._request("GET", "/users/me")

    def get_listing(self, listing_id):
        return self._request("GET", f"/listings/{listing_id}")

    def update_listing(self, shop_id, listing_id, fields):
        """updateListing (PATCH, form-urlencoded). Les tableaux (tags,
        materials) sont envoyés en valeurs séparées par des virgules."""
        form = {}
        for key, value in fields.items():
            if isinstance(value, (list, tuple)):
                value = ",".join(str(v) for v in value)
            elif isinstance(value, bool):
                value = "true" if value else "false"
            form[key] = value
        return self._request("PATCH", f"/shops/{shop_id}/listings/{listing_id}", form=form)

    def get_listing_inventory(self, listing_id):
        return self._request("GET", f"/listings/{listing_id}/inventory")

    def update_listing_inventory(self, listing_id, body):
        return self._request("PUT", f"/listings/{listing_id}/inventory", json_payload=body)
