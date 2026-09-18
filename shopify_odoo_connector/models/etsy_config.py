# -*- coding: utf-8 -*-
import logging

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .etsy_api_client import EtsyAPIClient, EtsyAPIError

_logger = logging.getLogger(__name__)

ETSY_SCOPE = "listings_r listings_w shops_r transactions_r"


class EtsyConfig(models.Model):
    _name = "etsy.config"
    _inherit = ["mail.thread"]
    _description = "Connexion Etsy (API directe, hors app Shopify tierce)"
    _rec_name = "name"

    name = fields.Char(default="Ma boutique Etsy", required=True)
    active = fields.Boolean(default=True)

    # Identifiants de l'app développeur Etsy (https://www.etsy.com/developers/register)
    client_id = fields.Char(string="Keystring (Client ID)", required=True)
    shop_id = fields.Char(
        string="ID boutique Etsy",
        required=True,
        help="Identifiant numérique de la boutique Etsy (visible dans l'URL du tableau de bord "
        "vendeur Etsy, ou via le bouton 'Récupérer mes infos boutique' une fois connecté).",
    )

    state = fields.Selection(
        [("draft", "Non connecté"), ("connected", "Connecté"), ("error", "Erreur")],
        default="draft",
        readonly=True,
    )
    last_error = fields.Text(readonly=True)

    access_token = fields.Char(copy=False)
    refresh_token = fields.Char(copy=False)
    token_expiry = fields.Datetime(copy=False)
    oauth_state = fields.Char(copy=False)
    oauth_code_verifier = fields.Char(copy=False)

    # Réglages requis par Etsy pour CHAQUE annonce, qu'Odoo n'a pas
    # nativement : appliqués par défaut, modifiables par ligne marketplace
    # (shopify.product.marketplace.content, onglet Etsy) si besoin plus tard.
    default_who_made = fields.Selection(
        [("i_did", "Moi (le vendeur)"), ("someone_else", "Quelqu'un d'autre"), ("collective", "Un collectif")],
        default="i_did",
        string="Qui a fabriqué (par défaut)",
    )
    default_when_made = fields.Selection(
        [
            ("made_to_order", "Fait sur commande"),
            ("2020_2025", "2020-2025"),
            ("2010_2019", "2010-2019"),
            ("before_2006", "Avant 2006"),
        ],
        default="2020_2025",
        string="Quand fabriqué (par défaut)",
    )
    default_taxonomy_id = fields.Integer(
        string="Catégorie Etsy par défaut (taxonomy_id)",
        help="Utilisez le bouton 'Voir les catégories Etsy' pour trouver l'ID correspondant à "
        "vos produits.",
    )
    default_shipping_profile_id = fields.Char(
        string="Profil d'expédition par défaut",
        help="Utilisez le bouton 'Voir mes profils d'expédition' pour récupérer cet ID depuis "
        "votre boutique Etsy (un profil doit déjà exister côté Etsy).",
    )
    is_supply = fields.Boolean(string="Fourniture/matériel (pas un produit fini)")

    # ------------------------------------------------------------------
    # Client API
    # ------------------------------------------------------------------
    def get_client(self):
        self.ensure_one()
        if not self.access_token:
            raise UserError(_("Connectez d'abord cette boutique Etsy via OAuth."))
        if self.token_expiry and fields.Datetime.now() >= self.token_expiry:
            self._refresh_token()
        return EtsyAPIClient(self.client_id, self.access_token)

    def _refresh_token(self):
        self.ensure_one()
        try:
            token_data = EtsyAPIClient.refresh_access_token(self.client_id, self.refresh_token)
        except EtsyAPIError as exc:
            self.write({"state": "error", "last_error": str(exc)})
            raise UserError(
                _("Échec du rafraîchissement du token Etsy : %s. Reconnectez la boutique.") % exc
            ) from exc
        self.write(
            {
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token", self.refresh_token),
                "token_expiry": fields.Datetime.now()
                + timedelta(seconds=max(int(token_data.get("expires_in", 3600)) - 60, 60)),
            }
        )

    # ------------------------------------------------------------------
    # OAuth 2.0 + PKCE
    # ------------------------------------------------------------------
    def action_connect_oauth(self):
        self.ensure_one()
        if not self.client_id:
            raise UserError(_("Renseignez le Keystring (Client ID) avant de vous connecter."))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        redirect_uri = f"{base_url}/etsy/oauth/callback"
        import secrets as _secrets

        state = _secrets.token_urlsafe(24)
        code_verifier, code_challenge = EtsyAPIClient.generate_pkce_pair()
        self.write({"oauth_state": state, "oauth_code_verifier": code_verifier})
        authorize_url = EtsyAPIClient.build_authorize_url(
            self.client_id, redirect_uri, ETSY_SCOPE, state, code_challenge
        )
        return {"type": "ir.actions.act_url", "url": authorize_url, "target": "self"}

    def _oauth_complete(self, code):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        redirect_uri = f"{base_url}/etsy/oauth/callback"
        token_data = EtsyAPIClient.exchange_code_for_token(
            self.client_id, redirect_uri, code, self.oauth_code_verifier
        )
        expires_in = int(token_data.get("expires_in", 3600))
        self.write(
            {
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "token_expiry": fields.Datetime.now() + timedelta(seconds=max(expires_in - 60, 60)),
                "state": "connected",
                "last_error": False,
            }
        )

    # ------------------------------------------------------------------
    # Aides pour trouver les IDs requis par Etsy (à utiliser une fois)
    # ------------------------------------------------------------------
    def action_fetch_shop_info(self):
        self.ensure_one()
        client = self.get_client()
        try:
            shop = client.get_shop(self.shop_id)
        except EtsyAPIError as exc:
            raise UserError(str(exc)) from exc
        self.message_post(
            body=_("Boutique Etsy connectée : %s (shop_id confirmé : %s)")
            % (shop.get("shop_name"), shop.get("shop_id"))
        )

    def action_fetch_shipping_profiles(self):
        self.ensure_one()
        client = self.get_client()
        try:
            data = client.get_shipping_profiles(self.shop_id)
        except EtsyAPIError as exc:
            raise UserError(str(exc)) from exc
        profiles = data.get("results", [])
        if not profiles:
            raise UserError(
                _(
                    "Aucun profil d'expédition trouvé sur cette boutique Etsy. "
                    "Créez-en un d'abord depuis le tableau de bord Etsy "
                    "(Paramètres de la boutique > Expédition)."
                )
            )
        lines = "\n".join(
            f"- {p.get('title')} : ID {p.get('shipping_profile_id')}" for p in profiles
        )
        self.message_post(body=_("Profils d'expédition Etsy disponibles :\n%s") % lines)

    def action_fetch_taxonomy(self):
        self.ensure_one()
        client = self.get_client()
        try:
            data = client.get_seller_taxonomy()
        except EtsyAPIError as exc:
            raise UserError(str(exc)) from exc
        nodes = data.get("results", [])[:40]
        lines = "\n".join(f"- {n.get('name')} : ID {n.get('id')}" for n in nodes)
        self.message_post(
            body=_(
                "Premières catégories Etsy (taxonomy_id) — liste complète bien plus longue, "
                "affinez au besoin par sous-catégorie :\n%s"
            )
            % lines
        )


class EtsyListingLink(models.Model):
    _name = "etsy.listing.link"
    _description = "Lien produit Odoo <-> annonce Etsy réelle"
    _rec_name = "etsy_listing_id"

    etsy_config_id = fields.Many2one("etsy.config", required=True, ondelete="cascade")
    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    etsy_listing_id = fields.Char(string="ID annonce Etsy", copy=False, index=True)
    etsy_shop_id = fields.Char(string="ID boutique Etsy", copy=False)
    last_sync = fields.Datetime()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "etsy_listing_product_uniq",
            "unique(etsy_config_id, product_tmpl_id)",
            "Ce produit a déjà une annonce Etsy liée pour cette configuration.",
        ),
    ]
