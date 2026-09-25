# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import logging
import re
import time

import requests

from odoo import api, fields, models, _

from .shopify_api_client import ShopifyAPIError
from .shopify_marketplace import _shopify_html_to_text

_logger = logging.getLogger(__name__)

IMAGE_DOWNLOAD_TIMEOUT = 20


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Un produit peut désormais être lié à PLUSIEURS boutiques Shopify à la
    # fois (une ligne shopify.product.link par boutique) : voir
    # shopify_multi_store.py. Les anciens champs "shopify_config_id" /
    # "shopify_product_id" uniques sont remplacés par ce one2many.
    shopify_link_ids = fields.One2many(
        "shopify.product.link", "product_tmpl_id", string="Boutiques Shopify liées"
    )
    shopify_config_ids = fields.Many2many(
        "shopify.config",
        relation="product_template_shopify_config_rel",
        column1="product_template_id",
        column2="shopify_config_id",
        compute="_compute_shopify_config_ids",
        string="Boutiques Shopify",
        # store=True est indispensable pour pouvoir filtrer/grouper les
        # produits PAR BOUTIQUE dans les vues (un champ calculé non stocké
        # ne peut pas être utilisé dans un "Regrouper par" ou un filtre de
        # recherche côté base de données).
        store=True,
    )
    # Marque Shopify (champ "vendor" de l'API Shopify). Permet de
    # différencier les produits par marque (ex: Clérieu) en plus de la
    # boutique : un même compte peut avoir plusieurs boutiques et/ou
    # plusieurs marques vendues sur une même boutique.
    shopify_vendor = fields.Char(
        string="Marque Shopify",
        copy=False,
        index=True,
        help="Correspond au champ 'Vendor' du produit sur Shopify (marque).",
    )
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")
    shopify_sync_pending = fields.Boolean(default=False, copy=False)
    shopify_display = fields.Boolean(
        string="Afficher sur Shopify",
        default=False,
        help=(
            "Réglée automatiquement selon la marque : cochée pour "
            "\"Clérieu\", décochée pour toute autre marque. Décochée, ce "
            "produit n'est jamais envoyé/affiché sur Shopify : s'il y "
            "est déjà, il est automatiquement archivé (retiré du site "
            "en ligne)."
        ),
    )
    # ------------------------------------------------------------------
    # Différenciation par marketplace (Amazon, Etsy, eBay, ... jusqu'à
    # autant de marketplaces que nécessaire) SUR UNE SEULE boutique
    # Shopify. Voir models/shopify_marketplace.py pour le détail :
    # une ligne = une marketplace, aucun champ à ajouter au code pour
    # une nouvelle marketplace, juste une ligne dans la liste
    # "Shopify > Configuration > Marketplaces".
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # FICHE ACTIVE : quelle fiche (Amazon / Etsy) remplit les champs
    # standards du produit Shopify (titre, description, prix, photo, tags).
    # Modifiable dans Odoo OU dans Shopify (liste « Fiche active » de la
    # carte Métachamps) : les deux restent synchronisés.
    # ------------------------------------------------------------------
    shopify_push_pending = fields.Boolean(copy=False, index=True)
    shopify_push_config_ids = fields.Many2many(
        "shopify.config",
        relation="product_template_shopify_push_config_rel",
        column1="product_tmpl_id",
        column2="config_id",
        copy=False,
        string="Boutiques à renvoyer",
    )
    shopify_switch_pending = fields.Boolean(copy=False, index=True)
    shopify_available_marketplace_ids = fields.Many2many(
        "shopify.marketplace",
        compute="_compute_shopify_available_marketplace_ids",
    )
    shopify_active_marketplace_id = fields.Many2one(
        "shopify.marketplace",
        string="Fiche active sur Shopify",
        domain="[('id', 'in', shopify_available_marketplace_ids)]",
        copy=False,
        help="Fiche envoyée dans les champs standards du produit Shopify : "
        "Fiche Etsy = ce qu'OrderBridge envoie à Etsy ; Fiche Amazon = ce "
        "que l'app Amazon envoie à Amazon. Aussi modifiable dans Shopify "
        "(métachamp « Fiche active »). Vide = fiche en mode « champs "
        "standards » (Etsy par défaut).",
    )

    @api.depends("shopify_marketplace_content_ids.marketplace_id")
    def _compute_shopify_available_marketplace_ids(self):
        for template in self:
            template.shopify_available_marketplace_ids = template.shopify_marketplace_content_ids.marketplace_id

    shopify_marketplace_content_ids = fields.One2many(
        "shopify.product.marketplace.content",
        "product_tmpl_id",
        string="Contenu par marketplace",
    )

    # NOTE : la contrainte de longueur du titre Amazon (75 caractères) a
    # déménagé sur shopify.product.marketplace.content._check_amazon_title_length
    # (fichier shopify_marketplace.py) : depuis que chaque marketplace a
    # son propre produit Shopify dédié, le titre Amazon (effective_title
    # de la ligne marketplace) n'est plus forcément identique au nom du
    # produit Odoo (`name`), donc la limite doit porter sur le premier,
    # pas sur le second.

    @api.onchange("shopify_vendor")
    def _onchange_shopify_vendor(self):
        """Coche/décoche automatiquement "Afficher sur Shopify" dès la
        saisie de la marque dans le formulaire, avant même l'enregistrement
        (create()/write() font le même calcul côté serveur, y compris pour
        les imports Shopify et les mises à jour en masse)."""
        for template in self:
            template.shopify_display = self._shopify_display_for_vendor(template.shopify_vendor)

    @api.depends("shopify_link_ids.config_id")
    def _compute_shopify_config_ids(self):
        for template in self:
            template.shopify_config_ids = template.shopify_link_ids.config_id

    def _shopify_get_link(self, config):
        """Retourne (ou vide) le lien vers `config` pour ce produit."""
        self.ensure_one()
        if not config:
            return self.env["shopify.product.link"]
        return self.shopify_link_ids.filtered(lambda l: l.config_id == config)[:1]

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config, updated_at_min=None):
        """Importe les produits de la boutique Shopify `config`.

        Si `updated_at_min` est fourni (utilisé par la synchro planifiée),
        seuls les produits modifiés depuis cette date sont récupérés :
        import incrémental, rapide, adapté à une exécution fréquente.
        Sans ce paramètre (bouton manuel, import initial), tout le
        catalogue est importé."""
        client = config.get_client()
        params = {"limit": 250}
        if updated_at_min:
            params["updated_at_min"] = fields.Datetime.to_string(updated_at_min)
        products = client.rest_get_with_pagination("/products.json", params=params)
        for shopify_product in products:
            try:
                # Chaque produit est traité dans son propre savepoint : si l'un
                # d'eux échoue (ex: conflit de variantes), la transaction
                # globale n'est pas corrompue et les produits suivants
                # continuent d'être importés normalement.
                with self.env.cr.savepoint():
                    self._shopify_create_or_update_from_data(shopify_product, config)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Erreur import produit Shopify %s", shopify_product.get("id"))
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "in",
                        "model_name": "product.template",
                        "shopify_object_type": "product",
                        "shopify_object_id": str(shopify_product.get("id")),
                        "state": "error",
                        "message": str(exc),
                    }
                )
        config.last_sync_products = fields.Datetime.now()
        if config.sync_inventory:
            try:
                self.env["product.product"].sudo().shopify_import_inventory_levels(config)
            except Exception:  # noqa: BLE001
                _logger.exception("Erreur lors de l'import des niveaux de stock Shopify")

    @staticmethod
    def _shopify_display_for_vendor(vendor):
        """Valeur automatique de la case "Afficher sur Shopify" déduite de
        la marque : cochée uniquement pour "Clérieu" (comparaison
        insensible à la casse/aux espaces), décochée pour toute autre
        marque (ou marque vide)."""
        return (vendor or "").strip().casefold() == "clérieu"

    @staticmethod
    def _shopify_vendor_matches_config_filter(vendor, config):
        """Version « brute » de _shopify_matches_brand_filter utilisable
        AVANT qu'un product.template existe (import Shopify -> Odoo) :
        on ne dispose encore que de la chaîne `vendor` reçue de Shopify,
        pas d'un enregistrement product.template."""
        vendor = (vendor or "").strip().casefold()

        exclude_raw = (config.export_brand_exclude or "").strip()
        if exclude_raw:
            excluded = {b.strip().casefold() for b in exclude_raw.split(",") if b.strip()}
            if vendor in excluded:
                return False

        include_raw = (config.export_brand_filter or "").strip()
        if include_raw:
            included = {b.strip().casefold() for b in include_raw.split(",") if b.strip()}
            if vendor not in included:
                return False

        return True

    def _shopify_create_or_update_from_data(self, data, config):
        Template = self.env["product.template"].sudo()
        Link = self.env["shopify.product.link"].sudo()
        # Produit Shopify DÉDIÉ à une marketplace (ex : copie Etsy poussée
        # par OrderBridge) : il est piloté exclusivement depuis Odoo. On ne
        # l'importe jamais (sinon : doublon de produit dans Odoo, ou fiche
        # Odoo écrasée par le contenu Etsy). Couvre le webhook
        # products/update déclenché quand OrderBridge écrit ses propres
        # métachamps (orderbridge/etsy_listing_id, dimensions, ...).
        # Double contrôle par "Type de produit" : le webhook
        # products/create du produit dédié peut arriver AVANT que la
        # transaction Odoo qui l'a créé soit validée (lien pas encore
        # visible) ; sans ce test, on créerait un doublon dans Odoo.
        dedicated_types = {
            (t or "").strip().lower()
            for t in self.env["shopify.marketplace"].sudo().search(
                [("shopify_publish_mode", "=", "dedicated")]
            ).mapped("shopify_product_type")
            if t
        }
        if (data.get("product_type") or "").strip().lower() in dedicated_types or self.env[
            "shopify.marketplace.product.link"
        ].sudo().search_count(
            [
                ("config_id", "=", config.id),
                ("shopify_product_id", "=", str(data.get("id"))),
            ]
        ):
            _logger.debug(
                "Produit Shopify %s ignoré à l'import : produit dédié à une marketplace.",
                data.get("id"),
            )
            return
        link = Link.search(
            [
                ("shopify_product_id", "=", str(data["id"])),
                ("config_id", "=", config.id),
            ],
            limit=1,
        )
        incoming_vendor = (data.get("vendor") or "").strip()
        if not self._shopify_vendor_matches_config_filter(incoming_vendor, config):
            # Marque non autorisée par les filtres de la boutique (import
            # Shopify -> Odoo) : on n'importe/ne met pas à jour ce produit
            # dans Odoo. S'il existait déjà (marque changée depuis côté
            # Shopify), on le retire aussi de la liste "Produits Shopify".
            _logger.info(
                "Produit Shopify %s ignoré à l'import pour la boutique %s : "
                "marque '%s' non autorisée par les filtres (inclure='%s', "
                "exclure='%s').",
                data.get("id"),
                config.display_name,
                incoming_vendor,
                config.export_brand_filter,
                config.export_brand_exclude,
            )
            if link:
                link.unlink()
            # On archive aussi immédiatement le produit sur Shopify lui-même
            # (au lieu d'attendre le prochain passage de la tâche planifiée
            # qui fait le même travail en rattrapage toutes les 15 min) :
            # ça couvre le cas où ce produit a été créé directement dans
            # Shopify (admin, Point de vente, app tierce...) et pas depuis
            # Odoo.
            if data.get("status") != "archived":
                try:
                    config.get_client().rest_put(
                        f"/products/{data['id']}.json",
                        {"product": {"id": int(data["id"]), "status": "archived"}},
                    )
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": config.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "shopify_object_type": "product",
                            "shopify_object_id": str(data["id"]),
                            "state": "success",
                            "message": _(
                                "Produit archivé automatiquement sur "
                                "Shopify : marque '%s' non autorisée par "
                                "les filtres de marque de la boutique."
                            )
                            % incoming_vendor,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.exception(
                        "Erreur archivage automatique Shopify du produit %s",
                        data.get("id"),
                    )
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": config.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "shopify_object_type": "product",
                            "shopify_object_id": str(data["id"]),
                            "state": "error",
                            "message": str(exc),
                        }
                    )
            return
        options = data.get("options", []) or []
        template_vals = {
            "name": data.get("title"),
            "sale_ok": True,
            "purchase_ok": True,
            "type": "consu",
            "is_storable": True,
            # La description Shopify (body_html) est reprise dans le champ
            # "Notes internes" d'Odoo (product.template.description).
            "description": data.get("body_html") or "",
        }
        # La marque ("vendor" côté Shopify) est toujours resynchronisée :
        # c'est elle qui permet de distinguer vos différentes marques
        # (ex: Clérieu) une fois les produits importés dans Odoo.
        vendor = (data.get("vendor") or "").strip()
        if vendor:
            template_vals["shopify_vendor"] = vendor
            template_vals["shopify_display"] = self._shopify_display_for_vendor(vendor)
        link_vals = {
            "shopify_product_id": str(data["id"]),
            "shopify_handle": data.get("handle"),
            "config_id": config.id,
            "last_sync": fields.Datetime.now(),
        }
        ctx_self = self.with_context(shopify_sync=True)
        reused_existing = False
        keep_odoo_fiche = False
        if link and link.product_tmpl_id._shopify_apply_active_fiche_from_shopify(config, data.get("id")):
            # La fiche active a été changée DANS Shopify : Odoo vient de
            # renvoyer le produit avec la fiche choisie ; rien d'autre à
            # importer de cette notification (elle portait l'ancienne fiche).
            return
        if link:
            template = link.product_tmpl_id
            main = template._shopify_main_content()
            if main:
                # Modification faite DANS Shopify (titre, description, prix) :
                # reportée sur la fiche active (Fiches produits). Avant, elle
                # était systématiquement annulée : Odoo renvoyait son ancien
                # contenu vers Shopify quelques minutes plus tard.
                template._shopify_import_into_main_content(main, data, config)
            if main:
                # Le produit Shopify porte la fiche Etsy (champs standards) :
                # ne JAMAIS la réimporter sur la fiche Odoo (nom, description,
                # prix, photos) — la fiche Odoo et la fiche Amazon restent
                # intactes.
                keep_odoo_fiche = True
                template_vals.pop("name", None)
                template_vals.pop("description", None)
            # On ne touche pas aux attribute_line_ids d'un produit déjà importé
            # pour éviter d'écraser une configuration existante ; seule la
            # création initiale met en place les attributs/variantes.
            template.with_context(shopify_sync=True).write(
                {**template_vals, "shopify_last_sync": fields.Datetime.now()}
            )
            link.write(link_vals)
        else:
            matched_template = False
            if self._shopify_avoid_duplicate_products_enabled():
                matched_template = self._shopify_find_existing_template(data, config)
            if matched_template:
                template = matched_template
                template.with_context(shopify_sync=True).write(
                    {**template_vals, "shopify_last_sync": fields.Datetime.now()}
                )
                reused_existing = True
            else:
                attribute_lines = self._shopify_prepare_attribute_lines(options)
                if attribute_lines:
                    template_vals["attribute_line_ids"] = attribute_lines
                template_vals["shopify_last_sync"] = fields.Datetime.now()
                template = ctx_self.create(template_vals)
            link_vals["product_tmpl_id"] = template.id
            Link.with_context(shopify_sync=True).create(link_vals)

        self.with_context(shopify_keep_odoo_price=keep_odoo_fiche)._shopify_sync_variants(
            template, data.get("variants", []), config, options
        )
        if not keep_odoo_fiche:
            self._shopify_sync_images(template, data.get("images", []), data.get("variants", []), config)
        self._shopify_sync_category(template, data["id"], config)
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "product.template",
                "res_id": template.id,
                "shopify_object_type": "product",
                "shopify_object_id": str(data["id"]),
                "state": "success",
                "message": (
                    _("Produit Odoo existant réutilisé (anti-doublon) : %s") % template.name
                    if reused_existing
                    else False
                ),
            }
        )
        return template

    # ------------------------------------------------------------------
    # Catégorie : IMPORT Shopify -> Odoo uniquement
    # ------------------------------------------------------------------
    # La catégorie standard Shopify ("Product Category" / taxonomy, visible
    # sur la fiche produit Shopify, ex: "Sacs de shopping dans Sacs à main")
    # n'existe PAS dans l'API REST des produits (/products.json) : elle
    # n'est exposée que par l'API GraphQL, sur le champ `category` du
    # produit. On la récupère donc via une requête GraphQL dédiée, une fois
    # le produit importé/mis à jour.
    SHOPIFY_PRODUCT_CATEGORY_QUERY = """
        query getProductCategory($id: ID!) {
          product(id: $id) {
            category {
              id
              name
              fullName
            }
          }
        }
    """

    def _shopify_sync_category(self, template, shopify_product_id, config):
        """Reporte la catégorie standard Shopify du produit sur la
        catégorie Odoo (categ_id) du template. Sens unique (Shopify ->
        Odoo) : la catégorie Odoo n'est jamais renvoyée vers Shopify."""
        if not config.sync_categories:
            return
        client = config.get_client()
        gid = f"gid://shopify/Product/{shopify_product_id}"
        try:
            result = client.graphql(
                self.SHOPIFY_PRODUCT_CATEGORY_QUERY, variables={"id": gid}
            )
        except ShopifyAPIError as exc:
            _logger.warning(
                "Échec de la récupération de la catégorie Shopify pour le produit %s : %s",
                shopify_product_id,
                exc,
            )
            return
        product_data = (result or {}).get("product") or {}
        category = product_data.get("category") or {}
        # Depuis l'API 2024-07, Product.category est directement une
        # TaxonomyCategory (id, name, fullName). L'ancien sous-objet
        # productTaxonomyNode n'existe plus sur ce champ.
        shopify_category = category if category.get("id") else None
        if not shopify_category:
            return
        categ = (
            self.env["shopify.category.mapping"]
            .sudo()
            .get_or_create_odoo_category(shopify_category)
        )
        if categ and template.categ_id != categ:
            template.with_context(shopify_sync=True).write({"categ_id": categ.id})

    # ------------------------------------------------------------------
    # Anti-doublons : réutiliser un produit Odoo existant plutôt que d'en
    # créer un nouveau lorsqu'un produit équivalent (même SKU / code-barres
    # / nom) existe déjà mais n'est pas encore lié à Shopify.
    # ------------------------------------------------------------------
    def _shopify_avoid_duplicate_products_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "shopify_odoo_connector.avoid_duplicate_products", "True"
        ) in ("True", "1", 1, True)

    def _shopify_find_existing_template(self, data, config):
        """Ne s'applique qu'aux produits à variante unique (le cas de
        duplication le plus courant : un produit déjà saisi manuellement
        dans Odoo avant la connexion de la boutique, ou déjà importé pour
        une autre boutique). Pour les produits à plusieurs variantes, on ne
        tente pas de réconciliation automatique car la structure d'attributs
        pourrait ne pas correspondre.

        Si `config.share_catalog` est activé, un produit déjà lié à une
        AUTRE boutique Shopify est également un candidat valide : on lui
        ajoute simplement un lien supplémentaire (catalogue partagé entre
        plusieurs boutiques/marques) plutôt que d'en créer un doublon. Par
        défaut (catalogue non partagé), seuls les produits pas encore liés à
        AUCUNE boutique sont proposés, pour ne jamais fusionner par erreur
        deux produits distincts de deux marques différentes."""
        variants = data.get("variants", []) or []
        if len(variants) > 1:
            return False

        Variant = self.env["product.product"].sudo()
        Template = self.env["product.template"].sudo()
        share = config.share_catalog

        def _is_candidate(template):
            if not template:
                return False
            if template._shopify_get_link(config):
                return False
            if not share and template.shopify_link_ids:
                return False
            return True

        # La marque ("vendor") du produit Shopify importé : si elle est
        # renseignée à la fois sur le produit importé et sur le candidat
        # Odoo, elle doit correspondre. Cela évite de fusionner par erreur
        # deux produits de MARQUES différentes qui portent le même nom / la
        # même référence (ex: un même nom de produit chez Clérieu et chez
        # une autre marque).
        vendor = (data.get("vendor") or "").strip()

        def _vendor_matches(template):
            if not vendor or not template.shopify_vendor:
                return True
            return template.shopify_vendor.strip().lower() == vendor.lower()

        codes = [v.get("sku") for v in variants if v.get("sku")]
        if codes:
            for variant in Variant.search([("default_code", "in", codes)], limit=20):
                if _is_candidate(variant.product_tmpl_id) and _vendor_matches(
                    variant.product_tmpl_id
                ):
                    return variant.product_tmpl_id

        barcodes = [v.get("barcode") for v in variants if v.get("barcode")]
        if barcodes:
            for variant in Variant.search([("barcode", "in", barcodes)], limit=20):
                if _is_candidate(variant.product_tmpl_id) and _vendor_matches(
                    variant.product_tmpl_id
                ):
                    return variant.product_tmpl_id

        name = (data.get("title") or "").strip()
        if name:
            for template in Template.search([("name", "=", name)], limit=20):
                if _is_candidate(template) and _vendor_matches(template):
                    return template

        return False

    # ------------------------------------------------------------------
    # Mapping des options Shopify <-> attributs/valeurs Odoo
    # ------------------------------------------------------------------
    SHOPIFY_SIMPLE_OPTION_NAME = "Title"
    SHOPIFY_SIMPLE_OPTION_VALUE = "Default Title"

    def _shopify_is_simple_product(self, options):
        """Un produit Shopify sans réelle variante expose une option
        'Title' / 'Default Title' : dans ce cas on ne crée aucun attribut."""
        return (
            not options
            or (
                len(options) == 1
                and options[0].get("name") == self.SHOPIFY_SIMPLE_OPTION_NAME
                and options[0].get("values") == [self.SHOPIFY_SIMPLE_OPTION_VALUE]
            )
        )

    def _shopify_get_or_create_attribute(self, name):
        Attribute = self.env["product.attribute"].sudo()
        attribute = Attribute.search([("name", "=", name)], limit=1)
        if not attribute:
            attribute = Attribute.create({"name": name, "create_variant": "always"})
        return attribute

    def _shopify_get_or_create_attribute_value(self, attribute, name):
        Value = self.env["product.attribute.value"].sudo()
        value = Value.search(
            [("attribute_id", "=", attribute.id), ("name", "=", name)], limit=1
        )
        if not value:
            value = Value.create({"attribute_id": attribute.id, "name": name})
        return value

    def _shopify_prepare_attribute_lines(self, options):
        """Construit les commandes one2many attribute_line_ids à partir des
        options Shopify (ex: Size: [S, M, L], Color: [Rouge, Bleu]). Odoo
        génère alors automatiquement toutes les variantes (combinaisons)."""
        if self._shopify_is_simple_product(options):
            return []
        commands = []
        for option in options:
            name = option.get("name")
            values = option.get("values", [])
            if not name or not values:
                continue
            attribute = self._shopify_get_or_create_attribute(name)
            value_ids = [
                self._shopify_get_or_create_attribute_value(attribute, value_name).id
                for value_name in values
            ]
            commands.append((0, 0, {"attribute_id": attribute.id, "value_ids": [(6, 0, value_ids)]}))
        return commands

    def _shopify_match_variant_by_options(self, template, option_values):
        """Retrouve, parmi les variantes déjà générées par Odoo à partir des
        attribute_line_ids, celle qui correspond à la combinaison
        (option1, option2, option3) d'une variante Shopify."""
        wanted_names = {v.strip().lower() for v in option_values if v}
        if not wanted_names:
            return None
        for variant in template.product_variant_ids:
            variant_value_names = {
                value.name.strip().lower()
                for value in variant.product_template_attribute_value_ids.mapped(
                    "product_attribute_value_id"
                )
            }
            if variant_value_names == wanted_names:
                return variant
        return None

    def _shopify_sync_variants(self, template, variants_data, config, options=None):
        VariantLink = self.env["shopify.variant.link"].sudo()
        simple_product = self._shopify_is_simple_product(options)
        for variant_data in variants_data:
            variant_link = VariantLink.search(
                [
                    ("shopify_variant_id", "=", str(variant_data["id"])),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
            common_vals = {
                "default_code": variant_data.get("sku") or False,
                "barcode": variant_data.get("barcode") or False,
                "list_price": float(variant_data.get("price") or 0.0),
            }
            if self.env.context.get("shopify_keep_odoo_price"):
                # Prix Shopify = prix de la fiche Etsy : ne pas l'importer
                # comme prix Odoo.
                common_vals.pop("list_price")
            link_vals = {
                "shopify_variant_id": str(variant_data["id"]),
                "shopify_inventory_item_id": str(variant_data.get("inventory_item_id") or ""),
                "config_id": config.id,
            }
            if variant_link:
                variant_link.product_id.with_context(shopify_sync=True).write(common_vals)
                variant_link.write(link_vals)
                continue

            if simple_product:
                # Produit sans option réelle : une seule variante par défaut,
                # déjà créée automatiquement par Odoo à la création du template.
                default_variant = template.product_variant_ids[:1]
                if default_variant and not default_variant._shopify_get_variant_link(config):
                    default_variant.with_context(shopify_sync=True).write(common_vals)
                    link_vals["product_id"] = default_variant.id
                    VariantLink.with_context(shopify_sync=True).create(link_vals)
                else:
                    _logger.warning(
                        "Produit simple sans variante libre pour la variante Shopify %s (produit %s)",
                        variant_data.get("id"),
                        template.id,
                    )
                continue

            # Produit avec options : la variante correspondante a déjà été
            # générée par Odoo via attribute_line_ids, on la retrouve par
            # combinaison de valeurs plutôt que d'en créer une nouvelle.
            option_values = [
                variant_data.get("option1"),
                variant_data.get("option2"),
                variant_data.get("option3"),
            ]
            matched = self._shopify_match_variant_by_options(template, option_values)
            if matched:
                matched.with_context(shopify_sync=True).write(common_vals)
                link_vals["product_id"] = matched.id
                VariantLink.with_context(shopify_sync=True).create(link_vals)
            else:
                _logger.warning(
                    "Aucune variante Odoo ne correspond à la combinaison Shopify %s (produit %s, options %s)",
                    variant_data.get("id"),
                    template.id,
                    option_values,
                )

    # ------------------------------------------------------------------
    # Photos : téléchargement + synchronisation (principale, galerie, variantes)
    # ------------------------------------------------------------------
    @staticmethod
    def _shopify_download_image_base64(url):
        """Télécharge une image Shopify (URL publique CDN) et la renvoie en base64,
        prête à être assignée à un champ binaire Odoo (image_1920, etc.)."""
        try:
            response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            _logger.warning("Échec du téléchargement de l'image Shopify %s : %s", url, exc)
            return False
        return base64.b64encode(response.content)

    def _shopify_sync_images(self, template, images_data, variants_data, config):
        if not images_data:
            return
        images_data = sorted(images_data, key=lambda img: img.get("position", 0))

        # --- Image principale (position 1) ---
        # NB : l'image (image_1920) est un champ partagé au niveau du
        # produit Odoo ; si ce produit est lié à plusieurs boutiques, la
        # dernière boutique synchronisée « gagne ». shopify_main_image_id
        # est suivi par lien (par boutique) pour ne retélécharger que si
        # l'image a changé côté CETTE boutique.
        link = template._shopify_get_link(config)
        main_image = images_data[0]
        if not link or str(main_image.get("id")) != link.shopify_main_image_id:
            content = self._shopify_download_image_base64(main_image.get("src"))
            if content:
                template.with_context(shopify_sync=True).write({"image_1920": content})
                if link:
                    link.write(
                        {
                            "shopify_main_image_id": str(main_image.get("id")),
                            "shopify_main_image_hash": self._shopify_hash(content),
                        }
                    )

        # --- Galerie (images supplémentaires) ---
        ProductImage = self.env["product.image"].sudo()
        for position, extra_image in enumerate(images_data[1:], start=2):
            existing = ProductImage.search(
                [
                    ("shopify_image_id", "=", str(extra_image.get("id"))),
                    ("product_tmpl_id", "=", template.id),
                ],
                limit=1,
            )
            if existing:
                continue
            content = self._shopify_download_image_base64(extra_image.get("src"))
            if content:
                # Nom distinctif (position + éventuel texte alternatif
                # Shopify), plutôt que le nom du produit répété à
                # l'identique sur chaque photo : sinon impossible de
                # reconnaître une image dans une liste déroulante (ex :
                # le champ "Image" de "Contenu par marketplace").
                image_label = extra_image.get("alt") or f"Photo {position}"
                ProductImage.with_context(shopify_sync=True).create(
                    {
                        "name": f"{template.name} — {image_label}",
                        "image_1920": content,
                        "product_tmpl_id": template.id,
                        "shopify_image_id": str(extra_image.get("id")),
                        "shopify_image_hash": self._shopify_hash(content),
                    }
                )

        # --- Photos spécifiques par variante ---
        images_by_id = {str(img.get("id")): img for img in images_data}
        VariantLink = self.env["shopify.variant.link"].sudo()
        for variant_data in variants_data:
            image_id = variant_data.get("image_id")
            if not image_id:
                continue
            image_id = str(image_id)
            variant_image = images_by_id.get(image_id)
            if not variant_image:
                continue
            variant_link = VariantLink.search(
                [
                    ("shopify_variant_id", "=", str(variant_data["id"])),
                    ("config_id", "=", config.id),
                ],
                limit=1,
            )
            if not variant_link or variant_link.shopify_variant_image_id == image_id:
                continue
            content = self._shopify_download_image_base64(variant_image.get("src"))
            if content:
                variant_link.product_id.with_context(shopify_sync=True).write(
                    {"image_variant_1920": content}
                )
                variant_link.write(
                    {
                        "shopify_variant_image_id": image_id,
                        "shopify_variant_image_hash": self._shopify_hash(content),
                    }
                )

    # ------------------------------------------------------------------
    # Photos : EXPORT Odoo -> Shopify
    # ------------------------------------------------------------------
    @staticmethod
    def _shopify_hash(binary_b64):
        """Empreinte MD5 d'un champ binaire Odoo (base64), pour savoir si
        une image a réellement changé avant de la renvoyer vers Shopify
        (évite de re-uploader la même image à chaque écriture)."""
        if not binary_b64:
            return False
        return hashlib.md5(binary_b64).hexdigest()

    def _shopify_delete_image(self, config, shopify_image_id):
        """Supprime une image côté Shopify (utilisé quand une photo est
        supprimée dans Odoo)."""
        self.ensure_one()
        link = self._shopify_get_link(config)
        if not link or not link.shopify_product_id or not shopify_image_id:
            return
        client = config.get_client()
        try:
            client.rest_delete(
                f"/products/{link.shopify_product_id}/images/{shopify_image_id}.json"
            )
        except ShopifyAPIError as exc:
            _logger.warning(
                "Échec de la suppression de l'image Shopify %s (%s) : %s",
                shopify_image_id,
                config.name,
                exc,
            )

    def _shopify_push_main_image(self, config, link):
        """Envoie/actualise l'image principale vers Shopify : celle de la
        fiche « champs standards » (Etsy) si elle existe, sinon image_1920."""
        self.ensure_one()
        main_content = self._shopify_main_content()
        main_image = (main_content.effective_image if main_content else False) or self.image_1920
        if not main_image or not link or not link.shopify_product_id:
            return
        content_hash = self._shopify_hash(main_image)
        if content_hash and content_hash == link.shopify_main_image_hash:
            return  # image inchangée depuis le dernier envoi : rien à faire
        client = config.get_client()
        payload = {"image": {"attachment": main_image.decode()}}
        try:
            if link.shopify_main_image_id:
                result = client.rest_put(
                    f"/products/{link.shopify_product_id}/images/{link.shopify_main_image_id}.json",
                    payload,
                )
            else:
                result = client.rest_post(
                    f"/products/{link.shopify_product_id}/images.json", payload
                )
            new_image = result.get("image", {}) or {}
            link.write(
                {
                    "shopify_main_image_id": str(
                        new_image.get("id") or link.shopify_main_image_id
                    ),
                    "shopify_main_image_hash": content_hash,
                }
            )
        except ShopifyAPIError as exc:
            _logger.warning(
                "Échec de l'envoi de l'image principale vers Shopify (%s) : %s",
                config.name,
                exc,
            )

    def _shopify_fiche_images(self, content):
        """Photos (base64) de la fiche : image principale de la fiche, puis
        sa galerie (onglet Médias de la ligne ; à défaut, galerie produit)."""
        images = []
        if content.effective_image:
            images.append(content.effective_image)
        gallery = content.media_ids.sorted("sequence").mapped("image") or [
            img.image_1920 for img in self.product_template_image_ids if img.image_1920
        ]
        images.extend(img for img in gallery if img)
        return images

    def _shopify_push_fiche_images(self, config, link):
        """Remplace les photos communes du produit Shopify par celles de la
        fiche active, seulement si elles ont changé (empreinte globale)."""
        self.ensure_one()
        content = self._shopify_main_content()
        images = self._shopify_fiche_images(content)
        digest = hashlib.md5("|".join(self._shopify_hash(i) or "" for i in images).encode()).hexdigest()
        if digest == link.shopify_fiche_images_hash:
            return
        client = config.get_client()
        base = f"/products/{link.shopify_product_id}/images"
        # Photos à retirer : celles de la fiche précédente + celles envoyées
        # par le mode classique (image principale, galerie commune).
        old_ids = [i for i in (link.shopify_fiche_image_ids or "").split(",") if i]
        if link.shopify_main_image_id:
            old_ids.append(link.shopify_main_image_id)
        common = self.product_template_image_ids.filtered("shopify_image_id")
        old_ids += common.mapped("shopify_image_id")
        try:
            for image_id in dict.fromkeys(old_ids):
                try:
                    client.rest_delete(f"{base}/{image_id}.json")
                except ShopifyAPIError:
                    pass  # déjà supprimée côté Shopify
            common.with_context(shopify_sync=True).write(
                {"shopify_image_id": False, "shopify_image_hash": False}
            )
            new_ids = []
            for position, image in enumerate(images, start=1):
                data = image.decode() if isinstance(image, bytes) else image
                result = client.rest_post(f"{base}.json", {"image": {"attachment": data, "position": position}})
                image_id = str((result.get("image") or {}).get("id") or "")
                if image_id:
                    new_ids.append(image_id)
            link.write(
                {
                    "shopify_fiche_image_ids": ",".join(new_ids),
                    "shopify_fiche_images_hash": digest,
                    "shopify_main_image_id": False,
                    "shopify_main_image_hash": False,
                }
            )
        except ShopifyAPIError as exc:
            _logger.warning("Photos de la fiche active : échec pour %s : %s", self.display_name, exc)

    def _shopify_push_gallery_images(self, config, link, variant_only=False):
        """Envoie/actualise la galerie de photos vers Shopify : les photos
        communes du produit modèle (product_template_image_ids) ET les
        photos spécifiques à chaque variante (product_variant_image_ids —
        section native Odoo "Extra Variant Media", sur la fiche de chaque
        variante). Une photo dont `product_variant_id` est renseigné est
        attachée UNIQUEMENT à cette variante côté Shopify (variant_ids) ;
        les photos communes restent sans variant_ids, comme avant."""
        self.ensure_one()
        if not link or not link.shopify_product_id:
            return
        client = config.get_client()
        images = self.product_template_image_ids | self.product_variant_ids.product_variant_image_ids
        for image in images:
            if not image.image_1920:
                continue
            if variant_only and not image.product_variant_id:
                continue  # photo commune : gérée par la fiche active

            variant_ids_payload = []
            target_variant_ref = False
            if image.product_variant_id:
                variant_link = image.product_variant_id._shopify_get_variant_link(config)
                if variant_link and variant_link.shopify_variant_id:
                    variant_ids_payload = [int(variant_link.shopify_variant_id)]
                    target_variant_ref = variant_link.shopify_variant_id
                else:
                    # La variante ciblée n'est pas encore liée à CETTE
                    # boutique (pas encore poussée) : impossible d'attacher
                    # la photo à un ID Shopify qui n'existe pas encore. Elle
                    # sera envoyée au prochain passage, une fois la
                    # variante liée (ex: après le premier envoi complet du
                    # produit, qui crée d'abord les liens de variantes).
                    continue

            content_hash = self._shopify_hash(image.image_1920)
            unchanged = (
                content_hash
                and content_hash == image.shopify_image_hash
                and target_variant_ref == (image.shopify_image_variant_ref or False)
            )
            if unchanged:
                continue

            payload_image = {"attachment": image.image_1920.decode()}
            if image.shopify_image_id:
                # PUT (mise à jour) : on envoie explicitement variant_ids
                # (même vide) pour pouvoir aussi "détacher" une photo d'une
                # variante si product_variant_id est retiré.
                payload_image["variant_ids"] = variant_ids_payload
            elif variant_ids_payload:
                payload_image["variant_ids"] = variant_ids_payload
            payload = {"image": payload_image}
            try:
                if image.shopify_image_id:
                    result = client.rest_put(
                        f"/products/{link.shopify_product_id}/images/{image.shopify_image_id}.json",
                        payload,
                    )
                else:
                    result = client.rest_post(
                        f"/products/{link.shopify_product_id}/images.json", payload
                    )
                new_image = result.get("image", {}) or {}
                image.with_context(shopify_sync=True).write(
                    {
                        "shopify_image_id": str(
                            new_image.get("id") or image.shopify_image_id
                        ),
                        "shopify_image_hash": content_hash,
                        "shopify_image_variant_ref": target_variant_ref,
                    }
                )
            except ShopifyAPIError as exc:
                _logger.warning(
                    "Échec de l'envoi d'une image de galerie vers Shopify (%s) : %s",
                    config.name,
                    exc,
                )

    def _shopify_push_variant_images(self, config):
        """Envoie/actualise les photos spécifiques à chaque variante
        (image_variant_1920) vers Shopify, en les associant à la bonne
        variante Shopify via `variant_ids`."""
        self.ensure_one()
        link = self._shopify_get_link(config)
        if not link or not link.shopify_product_id:
            return
        client = config.get_client()
        for variant in self.product_variant_ids:
            if not variant.image_variant_1920:
                continue
            variant_link = variant._shopify_get_variant_link(config)
            if not variant_link or not variant_link.shopify_variant_id:
                continue
            content_hash = self._shopify_hash(variant.image_variant_1920)
            if content_hash and content_hash == variant_link.shopify_variant_image_hash:
                continue
            payload = {
                "image": {
                    "attachment": variant.image_variant_1920.decode(),
                    "variant_ids": [int(variant_link.shopify_variant_id)],
                }
            }
            try:
                if variant_link.shopify_variant_image_id:
                    result = client.rest_put(
                        f"/products/{link.shopify_product_id}/images/"
                        f"{variant_link.shopify_variant_image_id}.json",
                        payload,
                    )
                else:
                    result = client.rest_post(
                        f"/products/{link.shopify_product_id}/images.json", payload
                    )
                new_image = result.get("image", {}) or {}
                variant_link.write(
                    {
                        "shopify_variant_image_id": str(
                            new_image.get("id") or variant_link.shopify_variant_image_id
                        ),
                        "shopify_variant_image_hash": content_hash,
                    }
                )
            except ShopifyAPIError as exc:
                _logger.warning(
                    "Échec de l'envoi de la photo de variante vers Shopify (%s) : %s",
                    config.name,
                    exc,
                )

    def _shopify_push_images(self, config):
        """Point d'entrée unique : envoie image principale, galerie et
        photos de variantes vers `config`. Chaque sous-méthode compare une
        empreinte MD5 pour n'envoyer que ce qui a réellement changé."""
        self.ensure_one()
        link = self._shopify_get_link(config)
        if not link or not link.shopify_product_id:
            return
        if self._shopify_main_content():
            # Fiche active (Amazon / Etsy) : photo principale + galerie DE
            # LA FICHE ; les photos propres aux variantes restent gérées
            # comme avant.
            self._shopify_push_fiche_images(config, link)
            self._shopify_push_gallery_images(config, link, variant_only=True)
        else:
            self._shopify_push_main_image(config, link)
            self._shopify_push_gallery_images(config, link)
        self._shopify_push_variant_images(config)

    def _shopify_marketplace_metafield_specs(self):
        """Retourne la liste (namespace, key, valeur, type) des métachamps
        marketplace à pousser pour ce produit, à partir des lignes
        `shopify_marketplace_content_ids` (une ligne = une marketplace).
        Titre, description et prix sont TOUJOURS envoyés (valeur
        spécifique si renseignée, sinon repli automatique sur la donnée
        standard du produit - voir `_compute_effective_fields` côté
        popup pour le même principe affiché à l'écran) ; catégorie et
        image restent optionnels (pas de différenciation pour ce champ
        précis sur cette marketplace tant qu'il n'y a rien à
        renseigner)."""
        self.ensure_one()
        specs = []
        for content in self.shopify_marketplace_content_ids:
            code = content.marketplace_id.code
            if not code:
                continue
            namespace = f"marketplace_{code}"
            specs.append(
                (namespace, "title", content.title_override or self.name, "single_line_text_field")
            )
            description_value = _shopify_html_to_text(content.description_override) or _shopify_html_to_text(
                self.description
            )
            if description_value:
                specs.append((namespace, "description", description_value, "multi_line_text_field"))
            # Le prix est TOUJOURS envoyé (jamais "vide" côté Shopify) :
            # celui saisi sur la ligne marketplace si renseigné, sinon
            # automatiquement le prix de vente global du produit. Ainsi,
            # tant qu'aucun prix spécifique n'est nécessaire pour cette
            # marketplace, elle suit le prix standard du produit — y
            # compris quand celui-ci change ensuite (renvoi automatique
            # déjà déclenché par product.template.write() sur
            # `list_price`, voir _shopify_push_one()).
            specs.append(
                (
                    namespace,
                    "price",
                    f"{content._shopify_marketplace_effective_price():.2f}",
                    "number_decimal",
                )
            )
            if content.category_override:
                specs.append((namespace, "category", content.category_override, "single_line_text_field"))
            # Galerie : photos spécifiques si renseignées, sinon repli
            # automatique sur la galerie du produit (voir
            # _shopify_marketplace_media_urls). Toujours envoyée dès que
            # le produit a au moins une photo (principale ou galerie),
            # même sans ligne "Médias" spécifique créée pour cette
            # marketplace.
            media_urls = content._shopify_marketplace_media_urls()
            if media_urls:
                specs.append((namespace, "media_urls", ",".join(media_urls), "multi_line_text_field"))
            if content.image_override:
                image_url = content._shopify_marketplace_image_url()
                if image_url:
                    specs.append((namespace, "image_url", image_url, "url"))
            specs.extend(content._shopify_platform_metafield_specs(namespace))
        return specs

    def _shopify_push_marketplace_metafields(self, config, shopify_product_id):
        """Envoie (crée ou met à jour) les métachamps marketplace sur le
        produit Shopify `shopify_product_id`, un métachamp par
        marketplace/champ renseigné dans `shopify_marketplace_content_ids`.
        Ces métachamps ne remplacent PAS le title/body_html du produit
        Shopify (partagés par toute la boutique) : ils portent un texte à
        part, propre à chaque marketplace, que l'intégration
        correspondante (app Shopify ou API externe) doit lire pour
        construire l'annonce sur cette marketplace."""
        self.ensure_one()
        specs = self._shopify_marketplace_metafield_specs()
        client = config.get_client()
        try:
            existing = client.rest_get(f"/products/{shopify_product_id}/metafields.json")
        except ShopifyAPIError as exc:
            _logger.exception(
                "Impossible de lire les métachamps Shopify existants du produit %s",
                self.display_name,
            )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product metafields",
                    "shopify_object_id": shopify_product_id,
                    "state": "error",
                    "message": f"Échec lecture des métachamps existants : {exc}",
                }
            )
            return
        existing_map = {
            (mf.get("namespace"), mf.get("key")): mf.get("id")
            for mf in (existing.get("metafields") or [])
        }
        # Valeurs déjà présentes dans Shopify : on n'envoie QUE ce qui a
        # changé (moins d'appels = changement de fiche plus rapide, et
        # moins de notifications Shopify en retour).
        existing_values = {
            (mf.get("namespace"), mf.get("key")): mf.get("value")
            for mf in (existing.get("metafields") or [])
        }

        def _same(old, new, mtype):
            if old is None:
                return False
            if mtype == "number_decimal":
                try:
                    return abs(float(old) - float(new)) < 0.0001
                except (TypeError, ValueError):
                    return False
            return str(old) == str(new)
        wanted_keys = set()
        mf_errors = []
        to_send = []
        for namespace, key, value, mtype in specs:
            wanted_keys.add((namespace, key))
            existing_id = existing_map.get((namespace, key))
            if existing_id and _same(existing_values.get((namespace, key)), value, mtype):
                continue
            to_send.append((namespace, key, value, mtype))
        # Envoi GROUPÉ (25 métachamps par appel GraphQL metafieldsSet) au
        # lieu d'un appel REST par métachamp : bien plus rapide.
        product_gid = f"gid://shopify/Product/{shopify_product_id}"
        for start in range(0, len(to_send), 25):
            batch = to_send[start:start + 25]
            try:
                data = client.graphql(
                    """mutation($metafields: [MetafieldsSetInput!]!) {
                         metafieldsSet(metafields: $metafields) { userErrors { field message code } } }""",
                    variables={
                        "metafields": [
                            {"ownerId": product_gid, "namespace": ns, "key": k, "value": v, "type": t}
                            for ns, k, v, t in batch
                        ]
                    },
                )
                for error in ((data or {}).get("metafieldsSet") or {}).get("userErrors") or []:
                    mf_errors.append(f"{error.get('field')} : {error.get('message')}")
            except ShopifyAPIError as exc:
                mf_errors.append(f"{len(batch)} métachamp(s) : {exc}")
                _logger.exception("Erreur envoi métachamps Shopify pour le produit %s", self.display_name)
        if mf_errors:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product metafields",
                    "shopify_object_id": shopify_product_id,
                    "state": "error",
                    "message": "\n".join(mf_errors),
                }
            )
        elif specs:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product metafields",
                    "shopify_object_id": shopify_product_id,
                    "state": "success",
                    "message": f"{len(specs)} métachamp(s) marketplace envoyé(s) : "
                    + ", ".join(f"{ns}.{k}" for ns, k, _v, _t in specs),
                }
            )

        # Supprime les métachamps marketplace devenus obsolètes : ligne
        # supprimée dans "Contenu par marketplace", ou champ vidé (titre/
        # description/image) sur une ligne existante. Sans cette étape,
        # Shopify garde indéfiniment l'ancienne valeur. On ne touche
        # qu'aux métachamps de nos propres namespaces ("marketplace_..."),
        # jamais aux autres métachamps du produit.
        for (namespace, key), mf_id in existing_map.items():
            if not namespace or not namespace.startswith("marketplace_"):
                continue
            if (namespace, key) in wanted_keys:
                continue
            try:
                client.rest_delete(f"/metafields/{mf_id}.json")
            except ShopifyAPIError:
                _logger.exception(
                    "Erreur suppression métachamp Shopify obsolète %s.%s pour le produit %s",
                    namespace, key, self.display_name,
                )

    # ------------------------------------------------------------------
    # PRODUITS SHOPIFY DÉDIÉS PAR MARKETPLACE (Amazon, Etsy, ...)
    # ------------------------------------------------------------------
    # Contrairement aux métachamps marketplace ci-dessus (lisibles
    # uniquement par une app qui sait aller les chercher), chaque
    # marketplace obtient ici son PROPRE produit Shopify, avec son propre
    # title/body_html/variants/image — des champs standards que n'importe
    # quelle app tierce (Amazon, Etsy Integration - DPL, ...) sait lire
    # nativement. Le produit Odoo reste UNIQUE ; seul le nombre de
    # produits Shopify générés change (1 "par défaut" + 1 par marketplace
    # ayant une ligne "Contenu par marketplace").
    def _shopify_sync_marketplace_dedicated_products(self, config):
        """Crée/met à jour, sur `config`, un produit Shopify dédié pour
        chaque ligne "Contenu par marketplace" dont la marketplace est en
        mode "produit dédié" (Etsy), puis supprime les produits dédiés
        devenus inutiles (ligne supprimée, ou marketplace repassée en
        mode fiche principale / métachamps)."""
        self.ensure_one()
        dedicated_contents = self.shopify_marketplace_content_ids.filtered(
            lambda c: c.marketplace_id.active
            and c.marketplace_id.shopify_publish_mode == "dedicated"
        )
        for content in dedicated_contents:
            self._shopify_push_marketplace_product(content, config)
        self._shopify_cleanup_marketplace_dedicated_products(
            config=config, keep_marketplaces=dedicated_contents.marketplace_id
        )

    def _shopify_cleanup_marketplace_dedicated_products(self, config=None, keep_marketplaces=None):
        """Supprime les produits Shopify dédiés à une marketplace qui ne
        sont plus justifiés (voir _shopify_sync_marketplace_dedicated_products).
        Sans argument : supprime TOUS les produits dédiés de ce produit."""
        self.ensure_one()
        MPLink = self.env["shopify.marketplace.product.link"].sudo()
        domain = [("product_tmpl_id", "=", self.id)]
        if config:
            domain.append(("config_id", "=", config.id))
        if keep_marketplaces:
            domain.append(("marketplace_id", "not in", keep_marketplaces.ids))
        links = MPLink.search(domain)
        for link in links:
            if link.shopify_product_id:
                try:
                    link.config_id.get_client().rest_delete(
                        f"/products/{link.shopify_product_id}.json"
                    )
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": link.config_id.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": self.id,
                            "shopify_object_type": f"product ({link.marketplace_id.name}, doublon)",
                            "shopify_object_id": link.shopify_product_id,
                            "state": "success",
                            "message": "Produit Shopify dédié supprimé (plus de ligne marketplace en mode « produit dédié »).",
                        }
                    )
                except ShopifyAPIError:
                    _logger.exception(
                        "Échec suppression doublon marketplace dédié pour %s", self.display_name
                    )
            self.env["shopify.marketplace.variant.link"].sudo().search(
                [
                    ("config_id", "=", link.config_id.id),
                    ("marketplace_id", "=", link.marketplace_id.id),
                    ("product_id", "in", self.product_variant_ids.ids),
                ]
            ).unlink()
            link.unlink()

    # ------------------------------------------------------------------
    # ETSY EN DIRECT (mode "etsy_api") : 1 seul produit Shopify
    # ------------------------------------------------------------------
    def _shopify_orderbridge_listing_id(self, config, shopify_product_id):
        """Lit le métachamp orderbridge/etsy_listing_id qu'OrderBridge
        écrit sur le produit Shopify après un push / une synchro
        d'inventaire : c'est le n° de l'annonce Etsy liée à ce produit."""
        try:
            result = config.get_client().rest_get(
                f"/products/{shopify_product_id}/metafields.json",
                params={"namespace": "orderbridge"},
            )
        except ShopifyAPIError:
            _logger.warning(
                "Lecture du métachamp OrderBridge impossible pour %s", self.display_name
            )
            return False
        for metafield in result.get("metafields") or []:
            if metafield.get("namespace") == "orderbridge" and metafield.get("key") == "etsy_listing_id":
                value = str(metafield.get("value") or "").strip()
                return value or False
        return False

    def _shopify_push_etsy_listings(self, config=None, shopify_product_id=None, force=False):
        """Pour chaque ligne marketplace en mode « API Etsy » : retrouve
        l'annonce Etsy (n° saisi, sinon métachamp OrderBridge) et la met à
        jour avec le contenu de la ligne Etsy."""
        self.ensure_one()
        contents = self.shopify_marketplace_content_ids.filtered(
            lambda c: c.marketplace_id.active and c.marketplace_id.shopify_publish_mode == "etsy_api"
        )
        if not contents:
            return
        if config is None:
            link = self.shopify_link_ids.filtered("shopify_product_id")[:1]
            config = link.config_id
            shopify_product_id = link.shopify_product_id
        listing_id = False
        if config and shopify_product_id:
            listing_id = self._shopify_orderbridge_listing_id(config, shopify_product_id)
        for content in contents:
            content._etsy_api_push(
                listing_id=content.etsy_listing_id or listing_id, force=force, config=config
            )

    def _shopify_get_marketplace_link(self, content, config):
        self.ensure_one()
        return self.env["shopify.marketplace.product.link"].sudo().search(
            [
                ("config_id", "=", config.id),
                ("product_tmpl_id", "=", self.id),
                ("marketplace_id", "=", content.marketplace_id.id),
            ],
            limit=1,
        )

    def _shopify_marketplace_sync_variant_links(self, marketplace, config, shopify_variants):
        """Recrée/actualise la correspondance variante Odoo <-> variante
        Shopify DÉDIÉE à cette marketplace, à partir de la réponse Shopify
        (create ou update), en respectant le même ordre que celui utilisé
        pour construire `variants_payload` (voir
        `_shopify_push_marketplace_product`). Rejoué à CHAQUE envoi : une
        variante Shopify supprimée/recréée côté Shopify (ex : par une app
        tierce) est donc réparée automatiquement au prochain envoi, sans
        intervention manuelle (voir l'incident diagnostiqué en amont, où
        un lien périmé bloquait tout renvoi)."""
        self.ensure_one()
        VLink = self.env["shopify.marketplace.variant.link"].sudo()
        for variant, shopify_variant in zip(self.product_variant_ids, shopify_variants or []):
            new_id = str(shopify_variant.get("id") or "")
            if not new_id:
                continue
            existing = VLink.search(
                [
                    ("config_id", "=", config.id),
                    ("marketplace_id", "=", marketplace.id),
                    ("product_id", "=", variant.id),
                ],
                limit=1,
            )
            inventory_item_id = str(shopify_variant.get("inventory_item_id") or "")
            if existing:
                vals = {}
                if existing.shopify_variant_id != new_id:
                    vals["shopify_variant_id"] = new_id
                if inventory_item_id and existing.shopify_inventory_item_id != inventory_item_id:
                    vals["shopify_inventory_item_id"] = inventory_item_id
                if vals:
                    existing.write(vals)
            else:
                VLink.with_context(shopify_sync=True).create(
                    {
                        "config_id": config.id,
                        "marketplace_id": marketplace.id,
                        "product_id": variant.id,
                        "shopify_variant_id": new_id,
                        "shopify_inventory_item_id": inventory_item_id or False,
                    }
                )

    # Etsy accepte 10 photos maximum par annonce.
    _SHOPIFY_DEDICATED_MAX_IMAGES = 10

    def _shopify_marketplace_dedicated_images(self, content):
        """Liste ordonnée des photos (base64) du produit dédié : image
        principale de la ligne marketplace, puis sa galerie (ou, à défaut,
        la galerie du produit). Ce sont ces photos qu'OrderBridge enverra
        à Etsy (option "Images" de Product Push)."""
        self.ensure_one()
        images = []
        if content.effective_image:
            images.append(content.effective_image)
        gallery = content.media_ids.sorted("sequence").mapped("image") or [
            img.image_1920 for img in self.product_template_image_ids if img.image_1920
        ]
        images.extend(img for img in gallery if img)
        return images[: self._SHOPIFY_DEDICATED_MAX_IMAGES]

    def _shopify_push_marketplace_images(self, content, config, link):
        """Envoie TOUTES les photos de la marketplace (principale + galerie)
        vers le produit Shopify dédié. Suivi par empreinte globale : rien
        n'est renvoyé tant qu'aucune photo n'a changé ; dès qu'une photo
        change, la galerie du produit dédié est remplacée entièrement (pas
        d'accumulation de doublons)."""
        self.ensure_one()
        if not link or not link.shopify_product_id:
            return
        images = self._shopify_marketplace_dedicated_images(content)
        gallery_hash = hashlib.md5(
            "|".join(self._shopify_hash(img) or "" for img in images).encode()
        ).hexdigest()
        if gallery_hash == link.shopify_gallery_hash:
            return
        client = config.get_client()
        base = f"/products/{link.shopify_product_id}/images"
        try:
            existing = client.rest_get(f"{base}.json").get("images") or []
            for image in existing:
                client.rest_delete(f"{base}/{image['id']}.json")
            first_id = False
            for position, image_b64 in enumerate(images, start=1):
                data = image_b64.decode() if isinstance(image_b64, bytes) else image_b64
                result = client.rest_post(
                    f"{base}.json", {"image": {"attachment": data, "position": position}}
                )
                if position == 1:
                    first_id = str((result.get("image") or {}).get("id") or "")
            link.write(
                {
                    "shopify_gallery_hash": gallery_hash,
                    "shopify_main_image_id": first_id or False,
                    "shopify_main_image_hash": self._shopify_hash(images[0]) if images else False,
                }
            )
        except ShopifyAPIError as exc:
            _logger.warning(
                "Échec de l'envoi des photos marketplace (%s / %s) : %s",
                config.name,
                content.marketplace_id.display_name,
                exc,
            )

    @staticmethod
    def _shopify_marketplace_tags(content):
        """Tags du produit dédié = tags Etsy saisis sur la ligne (13 max,
        20 caractères max chacun : limites Etsy). OrderBridge les pousse
        tels quels vers Etsy (option "Tags")."""
        raw = content.etsy_style_tags or ""
        tags = [t.strip()[:20] for t in raw.split(",") if t.strip()]
        return ", ".join(tags[:13])

    _SHOPIFY_WEIGHT_UNITS = {"kg": "kg", "g": "g", "lb": "lb", "lbs": "lb", "oz": "oz"}

    def _shopify_weight_and_unit(self, variant=None):
        """(poids, unité) du produit dans l'unité de poids Odoo, ou
        (0, False) si aucun poids n'est renseigné. Unités acceptées par
        Shopify et Etsy : kg, g, lb, oz."""
        self.ensure_one()
        record = variant or self
        weight = record.weight or (self.weight if variant else 0.0)
        if not weight or weight <= 0:
            return 0.0, False
        unit = self._SHOPIFY_WEIGHT_UNITS.get((self.weight_uom_name or "kg").strip().lower(), "kg")
        return round(weight, 3), unit

    def _shopify_variant_weight_vals(self, variant):
        weight, unit = self._shopify_weight_and_unit(variant)
        if not weight:
            return {}
        return {"weight": weight, "weight_unit": unit}

    @staticmethod
    def _shopify_norm_html(value):
        return " ".join(_shopify_html_to_text(value or "").split())

    def _shopify_import_into_main_content(self, main, data, config):
        """Reporte titre / description / prix modifiés dans Shopify sur la
        fiche marketplace qui occupe les champs standards du produit
        Shopify (`main`).

        Seule exception : une page Shopify restée ouverte pendant un
        changement de fiche (contenu PÉRIMÉ). Dans ce cas, on renvoie la
        fiche active vers Shopify au lieu d'importer l'ancien contenu."""
        self.ensure_one()
        incoming_title = (data.get("title") or "").strip()
        incoming_desc = data.get("body_html") or ""
        shopify_variants = data.get("variants") or []

        # 1) Contenu périmé ?
        other_titles = {
            (c.effective_title or "").strip()
            for c in self.shopify_marketplace_content_ids - main
        }
        stale = (
            self.shopify_switch_pending
            or self.shopify_push_pending
            or (
                incoming_title
                and incoming_title != (main.effective_title or "").strip()
                and incoming_title in other_titles
            )
        )
        if stale:
            self._shopify_queue_push()
            return False

        # 2) Titre / description -> fiche active
        vals = {}
        if incoming_title and incoming_title != (main.effective_title or "").strip():
            vals["title_override"] = incoming_title
        if self._shopify_norm_html(incoming_desc) != self._shopify_norm_html(main.effective_description):
            vals["description_override"] = incoming_desc

        # 3) Prix -> fiche active (ou ligne variante de la fiche)
        VLine = self.env["shopify.product.marketplace.variant"].sudo()
        single = len(self.product_variant_ids) == 1
        variant_price_changes = []
        for sv in shopify_variants:
            try:
                incoming_price = float(sv.get("price"))
            except (TypeError, ValueError):
                continue
            link = self.env["shopify.variant.link"].sudo().search(
                [("config_id", "=", config.id), ("shopify_variant_id", "=", str(sv.get("id")))],
                limit=1,
            )
            variant = link.product_id if link else (self.product_variant_ids[:1] if single else False)
            if not variant or variant.product_tmpl_id != self:
                continue
            if abs(main._shopify_main_variant_price(variant) - incoming_price) <= 0.001:
                continue
            if single:
                # Prix de la fiche tel que prix envoyé = prix Shopify.
                vals["price_override"] = incoming_price - (variant.lst_price - self.list_price)
            else:
                variant_price_changes.append((variant, incoming_price))

        changed = []
        if vals:
            main.with_context(shopify_sync=True).write(vals)
            changed += list(vals)
        for variant, price in variant_price_changes:
            line = main.variant_ids.filtered(lambda l, v=variant: l.product_id == v)[:1]
            if line:
                line.with_context(shopify_sync=True).write({"price_override": price})
            else:
                VLine.with_context(shopify_sync=True).create(
                    {"content_id": main.id, "product_id": variant.id, "price_override": price}
                )
            changed.append(f"prix {variant.display_name}")
        if changed:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "in",
                    "model_name": "shopify.product.marketplace.content",
                    "res_id": main.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": str(data.get("id")),
                    "state": "success",
                    "message": (
                        f"Modifications Shopify reportées sur la fiche "
                        f"{main.marketplace_id.name} : {', '.join(changed)}"
                    ),
                }
            )
        return True

    SHOPIFY_TAXONOMY_SEARCH_QUERY = """
        query searchTaxonomy($q: String!) {
          taxonomy {
            categories(first: 20, search: $q) {
              nodes { id name fullName isLeaf }
            }
          }
        }
    """
    SHOPIFY_PRODUCT_TYPE_QUERY = """
        query productType($id: ID!) {
          product(id: $id) { productType category { id } }
        }
    """
    SHOPIFY_PRODUCT_CATEGORY_MUTATION = """
        mutation setCategory($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id category { id fullName } }
            userErrors { field message }
          }
        }
    """

    @staticmethod
    def _shopify_norm_label(value):
        """Minuscules, sans accents ni ponctuation superflue : « Vêtements »
        == « vetements »."""
        import unicodedata
        value = unicodedata.normalize("NFKD", value or "")
        value = "".join(c for c in value if not unicodedata.combining(c))
        return " ".join(re.sub(r"[^\w>&]+", " ", value.casefold()).split())

    def _shopify_search_taxonomy(self, client, text):
        """Recherche dans la taxonomie Shopify, en demandant les libellés en
        français puis sans préférence de langue."""
        nodes = []
        for headers in ({"Accept-Language": "fr"}, {}):
            payload = {"query": self.SHOPIFY_TAXONOMY_SEARCH_QUERY, "variables": {"q": text}}
            response = requests.post(
                f"{client.base_url}/graphql.json",
                headers=dict(client._headers(), **headers),
                json=payload,
                timeout=client.timeout,
            )
            if response.status_code >= 400:
                raise ShopifyAPIError(
                    f"Recherche de catégorie Shopify : {response.status_code} {response.text[:300]}",
                    status_code=response.status_code,
                )
            data = client._safe_json(response)
            if data.get("errors"):
                raise ShopifyAPIError(f"Recherche de catégorie Shopify : {data['errors']}")
            found = ((((data.get("data") or {}).get("taxonomy") or {}).get("categories") or {}).get("nodes")) or []
            known = {n["id"] for n in nodes}
            nodes += [n for n in found if n.get("id") not in known]
        return nodes

    def _shopify_resolve_taxonomy_category(self, client, content):
        """Trouve la catégorie standard Shopify correspondant EXACTEMENT à la
        « Catégorie marketplace » de la fiche. Accepte :
        - un ID gid://shopify/TaxonomyCategory/... (utilisé tel quel) ;
        - un nom (« Vêtements », « Clothing ») ;
        - un chemin (« Apparel & Accessories > Clothing »).

        Plus AUCUNE devinette : la recherche Shopify renvoie des résultats
        approximatifs (ex : « Vêtements » -> « Sais » dans Armes d'arts
        martiaux), l'ancienne version prenait le premier résultat. Sans
        correspondance exacte, rien n'est envoyé et les suggestions sont
        notées dans le journal.

        Retourne (gid, chemin, suggestions)."""
        text = (content.category_override or "").strip()
        if text.startswith("gid://shopify/TaxonomyCategory/"):
            return text, text, []
        if content.shopify_category_gid and content.shopify_category_source == text:
            return content.shopify_category_gid, content.shopify_category_fullname, []
        if not text:
            return False, False, []
        leaf = text.split(">")[-1].strip()
        nodes = self._shopify_search_taxonomy(client, leaf)
        wanted_full = self._shopify_norm_label(" > ".join(p.strip() for p in text.split(">")))
        wanted_leaf = self._shopify_norm_label(leaf)
        is_path = ">" in text
        matches = [
            n for n in nodes
            if self._shopify_norm_label(n.get("fullName")) == wanted_full
            or (not is_path and self._shopify_norm_label(n.get("name")) == wanted_leaf)
        ]
        if not matches:
            return False, False, nodes[:8]
        # Plusieurs catégories de même nom : la moins profonde (la plus
        # générale) l'emporte, sauf si un chemin complet a été donné.
        best = sorted(matches, key=lambda n: (n.get("fullName") or "").count(">"))[0]
        full_name = best.get("fullName") or best.get("name")
        content.with_context(shopify_sync=True).write(
            {
                "shopify_category_gid": best["id"],
                "shopify_category_fullname": full_name,
                "shopify_category_source": text,
            }
        )
        return best["id"], full_name, []

    def _shopify_push_taxonomy_category(self, config, shopify_product_id, content):
        """Envoie la « Catégorie marketplace » de la fiche active dans le
        champ CATÉGORIE standard du produit Shopify (et non dans Type).
        Si Type contient encore l'ancienne valeur envoyée par erreur
        (= la catégorie), il est vidé."""
        self.ensure_one()
        if not content.shopify_category_id and not (content.category_override or "").strip():
            return
        client = config.get_client()
        product_gid = f"gid://shopify/Product/{shopify_product_id}"

        def _log(state, message):
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product_category",
                    "shopify_object_id": shopify_product_id,
                    "state": state,
                    "message": message,
                }
            )

        try:
            if content.shopify_category_id:
                # Catégorie choisie dans la liste Shopify : identifiant exact.
                category_gid = content.shopify_category_id.gid
                full_name = content.shopify_category_id.full_name
                suggestions = []
            else:
                category_gid, full_name, suggestions = self._shopify_resolve_taxonomy_category(client, content)
            if not category_gid:
                hint = (
                    " Catégories Shopify proches : "
                    + " | ".join(f"{n.get('fullName')} ({n.get('id')})" for n in suggestions)
                    if suggestions
                    else ""
                )
                _log(
                    "error",
                    f"Aucune catégorie Shopify ne correspond exactement à "
                    f"« {content.category_override} » : catégorie NON envoyée. "
                    "Saisissez le nom exact d'une catégorie Shopify (ex : "
                    "« Clothing », « Tote Bags »), son chemin complet, ou collez "
                    "son ID gid://shopify/TaxonomyCategory/..." + hint,
                )
                return
            current = (client.graphql(self.SHOPIFY_PRODUCT_TYPE_QUERY, variables={"id": product_gid}) or {}).get(
                "product"
            ) or {}
            product_input = {"id": product_gid}
            if ((current.get("category") or {}).get("id")) != category_gid:
                product_input["category"] = category_gid
            if content.category_override and (current.get("productType") or "").strip() == content.category_override.strip():
                product_input["productType"] = ""
            if len(product_input) == 1:
                return  # déjà à jour
            result = client.graphql(
                self.SHOPIFY_PRODUCT_CATEGORY_MUTATION, variables={"input": product_input}
            )
            errors = ((result or {}).get("productUpdate") or {}).get("userErrors") or []
            if errors:
                _log("error", "; ".join(e.get("message", "") for e in errors))
            else:
                _log("success", f"Catégorie Shopify : {full_name}")
        except ShopifyAPIError as exc:
            _log("error", str(exc))

    @api.model
    def _shopify_handle_product_deleted(self, config, shopify_product_id):
        """Produit supprimé dans Shopify (webhook products/delete OU
        rattrapage de la tâche planifiée) :
        - produit dédié marketplace : on oublie le lien (recréé au
          prochain envoi) ;
        - produit principal : lien désactivé, et produit Odoo ARCHIVÉ s'il
          n'est plus lié à aucune autre boutique."""
        ctx = self.with_context(shopify_sync=True).sudo()
        shopify_product_id = str(shopify_product_id)
        mp_links = ctx.env["shopify.marketplace.product.link"].search(
            [("shopify_product_id", "=", shopify_product_id), ("config_id", "=", config.id)]
        )
        if mp_links:
            ctx.env["shopify.marketplace.variant.link"].search(
                [
                    ("config_id", "=", config.id),
                    ("marketplace_id", "in", mp_links.marketplace_id.ids),
                    ("product_id", "in", mp_links.product_tmpl_id.product_variant_ids.ids),
                ]
            ).unlink()
            mp_links.unlink()
            return False
        link = ctx.env["shopify.product.link"].search(
            [("shopify_product_id", "=", shopify_product_id), ("config_id", "=", config.id)],
            limit=1,
        )
        if not link:
            return False
        template = link.product_tmpl_id
        # Liens SUPPRIMÉS (et non simplement désactivés) : un lien inactif
        # bloquait, via les contraintes d'unicité, la recréation du produit
        # sur Shopify si on désarchive le produit et qu'on le renvoie.
        # Les liens de variantes partent aussi, sinon le stock continuerait
        # d'être envoyé vers un produit qui n'existe plus.
        self.env["shopify.variant.link"].sudo().with_context(active_test=False).search(
            [("config_id", "=", config.id), ("product_id", "in", template.with_context(active_test=False).product_variant_ids.ids)]
        ).unlink()
        link.unlink()
        archived = False
        if not template.shopify_link_ids.filtered("active"):
            template.with_context(shopify_sync=True).write({"active": False, "sale_ok": False})
            archived = True
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "product.template",
                "res_id": template.id,
                "shopify_object_type": "product",
                "shopify_object_id": shopify_product_id,
                "state": "success",
                "message": (
                    f"Produit supprimé dans Shopify : « {template.name} » archivé dans Odoo."
                    if archived
                    else f"Produit supprimé dans Shopify : lien retiré (« {template.name} » "
                    "reste actif, lié à une autre boutique)."
                ),
            }
        )
        return archived

    @api.model
    def _shopify_archive_deleted_products(self, config):
        """Rattrapage (tâche planifiée) des suppressions Shopify dont le
        webhook n'est jamais arrivé. Par sécurité, rien n'est archivé si la
        liste des produits Shopify n'a pas pu être lue EN ENTIER."""
        client = config.get_client()
        try:
            expected = int(client.rest_get("/products/count.json").get("count", -1))
            products = client.rest_get_with_pagination(
                "/products.json", params={"limit": 250, "fields": "id"}, limit_pages=100000
            )
        except ShopifyAPIError as exc:
            _logger.warning("Rattrapage des suppressions ignoré (%s) : %s", config.name, exc)
            return
        existing_ids = {str(p.get("id")) for p in products if p.get("id")}
        if expected < 0 or len(existing_ids) < expected:
            _logger.warning(
                "Rattrapage des suppressions ignoré pour %s : liste Shopify "
                "incomplète (%s lus / %s attendus).",
                config.name, len(existing_ids), expected,
            )
            return
        links = self.env["shopify.product.link"].sudo().search(
            [("config_id", "=", config.id), ("shopify_product_id", "!=", False)]
        )
        mp_links = self.env["shopify.marketplace.product.link"].sudo().search(
            [("config_id", "=", config.id), ("shopify_product_id", "!=", False)]
        )
        missing = {
            l.shopify_product_id for l in (links | mp_links) if l.shopify_product_id not in existing_ids
        }
        for shopify_product_id in missing:
            with self.env.cr.savepoint():
                self._shopify_handle_product_deleted(config, shopify_product_id)
        if missing:
            _logger.info(
                "Boutique %s : %d produit(s) supprimé(s) dans Shopify traité(s).",
                config.name, len(missing),
            )

    def _shopify_refresh_variant_links(self, config, shopify_variants):
        """Crée les liens de variantes manquants et complète les
        `shopify_inventory_item_id` vides, à partir de la réponse Shopify
        (même ordre que `variants_payload` dans `_shopify_push_one`)."""
        self.ensure_one()
        VariantLink = self.env["shopify.variant.link"].sudo()
        for variant, sv in zip(self.product_variant_ids, shopify_variants):
            variant_id = str(sv.get("id") or "")
            item_id = str(sv.get("inventory_item_id") or "")
            if not variant_id:
                continue
            link = variant._shopify_get_variant_link(config)
            if not link:
                VariantLink.with_context(shopify_sync=True).create(
                    {
                        "product_id": variant.id,
                        "config_id": config.id,
                        "shopify_variant_id": variant_id,
                        "shopify_inventory_item_id": item_id or False,
                    }
                )
                continue
            vals = {}
            if link.shopify_variant_id != variant_id:
                vals["shopify_variant_id"] = variant_id
            if item_id and link.shopify_inventory_item_id != item_id:
                vals["shopify_inventory_item_id"] = item_id
            if vals:
                link.with_context(shopify_sync=True).write(vals)

    def _shopify_push_main_stock(self, config):
        """Envoie le stock Odoo de toutes les variantes du produit principal
        vers chaque emplacement Shopify mappé de la boutique."""
        self.ensure_one()
        locations = self.env["shopify.location"].sudo().search(
            [("config_id", "=", config.id), ("warehouse_id", "!=", False)]
        )
        if not locations:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "inventory_level",
                    "state": "error",
                    "message": (
                        "Stock non envoyé : aucun emplacement Shopify de la "
                        "boutique n'est mappé à un entrepôt Odoo."
                    ),
                }
            )
            return
        Product = self.env["product.product"].sudo()
        for variant in self.product_variant_ids:
            for warehouse in locations.warehouse_id:
                Product._shopify_push_inventory_for_warehouse(variant, warehouse)

    def _shopify_push_marketplace_stock(self, config):
        """Aligne le stock des variantes du produit dédié sur le stock
        Odoo réel (mêmes entrepôts que le produit principal), pour
        qu'OrderBridge / Etsy ne vendent jamais plus que le disponible."""
        self.ensure_one()
        locations = self.env["shopify.location"].sudo().search(
            [("config_id", "=", config.id), ("warehouse_id", "!=", False)]
        )
        Product = self.env["product.product"].sudo()
        for variant in self.product_variant_ids:
            for warehouse in locations.warehouse_id:
                Product._shopify_push_inventory_for_warehouse(variant, warehouse)

    def _shopify_push_marketplace_product(self, content, config):
        """Crée ou met à jour le produit Shopify DÉDIÉ à `content`
        (une marketplace précise) sur `config`, avec son propre titre,
        sa propre description, ses propres prix de variantes et sa propre
        image principale — jamais le produit Shopify "par défaut" de la
        boutique, ni la fiche produit Odoo."""
        self.ensure_one()
        content.ensure_one()
        if not self._shopify_matches_brand_filter(config):
            return
        link = self._shopify_get_marketplace_link(content, config)
        client = config.get_client()

        option_lines = self._shopify_export_option_lines()
        variants_payload = []
        for variant in self.product_variant_ids:
            mp_variant = content.variant_ids.filtered(lambda l, v=variant: l.product_id == v)[:1]
            variant_link = self.env["shopify.marketplace.variant.link"].sudo().search(
                [
                    ("config_id", "=", config.id),
                    ("marketplace_id", "=", content.marketplace_id.id),
                    ("product_id", "=", variant.id),
                ],
                limit=1,
            )
            price = (
                mp_variant.effective_price
                if mp_variant
                else content._shopify_marketplace_effective_price()
            )
            sku = (mp_variant.effective_sku if mp_variant else "") or variant.default_code or ""
            suffix = content.marketplace_id.shopify_sku_suffix or ""
            if sku and suffix and not sku.endswith(suffix):
                sku = f"{sku}{suffix}"
            variant_vals = {
                "id": (
                    int(variant_link.shopify_variant_id)
                    if variant_link and variant_link.shopify_variant_id
                    else None
                ),
                "price": f"{price:.2f}",
                "sku": sku,
                "barcode": variant.barcode or "",
                # Stock suivi par Shopify : indispensable pour que
                # OrderBridge lise/pousse une quantité vers Etsy.
                "inventory_management": "shopify",
            }
            variant_vals.update(self._shopify_variant_weight_vals(variant))
            if option_lines:
                option_values = self._shopify_variant_option_values(variant, option_lines)
                for index, value in enumerate(option_values, start=1):
                    variant_vals[f"option{index}"] = value or variant.display_name
            variants_payload.append(variant_vals)

        marketplace = content.marketplace_id
        payload_product = {
            "title": content.effective_title,
            "body_html": content.effective_description or "",
            "vendor": self.shopify_vendor or "",
            # Isole le produit dédié : collection automatique à filtrer
            # dans OrderBridge, et à exclure dans l'app Amazon.
            "product_type": marketplace.shopify_product_type or marketplace.name or "",
            "tags": self._shopify_marketplace_tags(content),
            "variants": variants_payload,
        }
        if option_lines:
            payload_product["options"] = [
                {"name": line.attribute_id.name} for line in option_lines
            ]
        shopify_product_id = link.shopify_product_id if link else False
        if not shopify_product_id and marketplace.shopify_hide_from_online_store:
            # À la création uniquement : non publié sur la boutique en
            # ligne (pas de doublon visible par vos clients). Le produit
            # reste "Actif" pour être visible dans OrderBridge.
            payload_product["published"] = False
        payload = {"product": payload_product}
        MPLink = self.env["shopify.marketplace.product.link"].sudo()
        try:
            if shopify_product_id:
                result = client.rest_put(
                    f"/products/{shopify_product_id}.json", payload
                )
            else:
                result = client.rest_post("/products.json", payload)
                new_id = result.get("product", {}).get("id")
                if not new_id:
                    return
                if link:
                    link.write({"shopify_product_id": str(new_id)})
                else:
                    link = MPLink.with_context(shopify_sync=True).create(
                        {
                            "config_id": config.id,
                            "product_tmpl_id": self.id,
                            "marketplace_id": content.marketplace_id.id,
                            "shopify_product_id": str(new_id),
                        }
                    )
                shopify_product_id = str(new_id)

            self._shopify_marketplace_sync_variant_links(
                content.marketplace_id, config, result.get("product", {}).get("variants", [])
            )
            link.write({"last_sync": fields.Datetime.now()})
            self._shopify_push_marketplace_images(content, config, link)
            self._shopify_push_marketplace_stock(config)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": f"product ({content.marketplace_id.name})",
                    "shopify_object_id": shopify_product_id,
                    "state": "success",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": f"product ({content.marketplace_id.name})",
                    "shopify_object_id": shopify_product_id or False,
                    "state": "error",
                    "message": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify
    # ------------------------------------------------------------------
    def action_shopify_push(self):
        default_config = self.env["shopify.config"]._shopify_default_config()
        for template in self:
            configs = template.shopify_link_ids.config_id
            if not configs:
                # Produit jamais encore lié à aucune boutique Shopify (créé
                # directement dans Odoo, sans passer par un import) : on
                # utilise la boutique par défaut, sinon le bouton "Envoyer
                # vers Shopify" ne ferait rien silencieusement.
                configs = default_config
            if not configs:
                _logger.warning(
                    "Aucune boutique Shopify configurée : impossible d'envoyer %s",
                    template.display_name,
                )
                continue
            for config in configs:
                template._shopify_push_one(config=config)

    def _shopify_export_option_lines(self):
        """Lignes d'attributs (attribute_line_ids) à exporter comme options
        Shopify. Un produit avec une seule variante n'a pas de réelle option
        (Shopify lui donnera automatiquement "Title" / "Default Title").
        Shopify limite à 3 options par produit au maximum : au-delà, seules
        les 3 premières sont envoyées."""
        self.ensure_one()
        if len(self.product_variant_ids) <= 1:
            return self.env["product.template.attribute.line"]
        return self.attribute_line_ids[:3]

    @staticmethod
    def _shopify_variant_option_values(variant, option_lines):
        """Valeurs (option1, option2, option3) d'une variante Odoo, dans le
        même ordre que `option_lines`, pour respecter la structure attendue
        par l'API Shopify (chaque variante doit renvoyer ses valeurs dans le
        même ordre que les options déclarées au niveau du produit)."""
        values = []
        for line in option_lines:
            ptav = variant.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_line_id == line
            )[:1]
            values.append(ptav.product_attribute_value_id.name if ptav else "")
        return values

    def _shopify_matches_brand_filter(self, config):
        """Retourne False si ce produit ne doit pas être envoyé/affiché sur
        `config`, que ce soit à cause de :
        - la case à cocher "Afficher sur Shopify" (shopify_display) décochée
          sur le produit lui-même (prioritaire, s'applique quelle que soit
          la marque) ;
        - export_brand_exclude (liste noire) : si la marque du produit y
          figure, on bloque toujours, même si elle figure aussi dans la
          liste blanche ;
        - export_brand_filter (liste blanche) : si renseignée, seules les
          marques listées passent.
        Sans case décochée ni filtre de marque configuré, tous les
        produits passent (comportement d'origine). Comparaison insensible
        à la casse/aux espaces, marques séparées par des virgules."""
        self.ensure_one()
        if not self.shopify_display:
            return False
        vendor = (self.shopify_vendor or "").strip().casefold()

        exclude_raw = (config.export_brand_exclude or "").strip()
        if exclude_raw:
            excluded = {b.strip().casefold() for b in exclude_raw.split(",") if b.strip()}
            if vendor in excluded:
                return False

        include_raw = (config.export_brand_filter or "").strip()
        if include_raw:
            included = {b.strip().casefold() for b in include_raw.split(",") if b.strip()}
            if vendor not in included:
                return False

        return True

    # ------------------------------------------------------------------
    # LISTE "Fiches marketplace" (métaobjets) sur le produit Shopify
    # ------------------------------------------------------------------
    def _shopify_fiche_values(self, content):
        """Champs du métaobjet "Fiche marketplace" pour une ligne."""
        self.ensure_one()
        marketplace = content.marketplace_id
        mode = marketplace.shopify_publish_mode
        if mode == "shopify_main":
            envoi = _("Champs standards du produit Shopify -> OrderBridge -> %s") % marketplace.name
        elif mode == "metafield":
            envoi = _("App %(name)s (métachamps marketplace_%(code)s.*)") % {
                "name": marketplace.name,
                "code": marketplace.code,
            }
        elif mode == "etsy_api":
            envoi = _("API Etsy directe depuis Odoo")
        else:
            envoi = dict(marketplace._fields["shopify_publish_mode"].selection).get(mode, "")
        values = {
            # Nom affiché dans le sélecteur Shopify : fiche + produit, pour
            # ne jamais confondre la Fiche Etsy de deux produits différents.
            "nom": _("Fiche %(mp)s — %(product)s") % {"mp": marketplace.name, "product": self.name},
            "marketplace": marketplace.name,
            "envoi": envoi,
            "titre": content.effective_title or self.name,
            "description": _shopify_html_to_text(content.effective_description or self.description),
            "prix": f"{content._shopify_marketplace_effective_price():.2f}",
        }
        image_url = content._shopify_marketplace_image_url()
        if image_url:
            values["image_url"] = image_url
        media_urls = content._shopify_marketplace_media_urls()
        if media_urls:
            values["photos"] = "\n".join(media_urls)
        tags = content.etsy_style_tags or content.amazon_search_terms
        if tags:
            values["tags"] = tags
        if content.amazon_bullet_points:
            values["points_cles"] = content.amazon_bullet_points
        details = [
            f"{label} : {value}"
            for label, value in (
                (_("Catégorie"), content.category_override),
                (_("Marque"), content.amazon_brand),
                ("GTIN", content.amazon_gtin),
                (_("Matériaux"), content.etsy_materials),
                (_("Qui l'a fabriqué"), dict(content._fields["etsy_who_made"].selection).get(content.etsy_who_made)),
                (_("Quand"), dict(content._fields["etsy_when_made"].selection).get(content.etsy_when_made)),
            )
            if value
        ]
        if details:
            values["details"] = "\n".join(details)
        return {k: (v or "") for k, v in values.items()}

    def _shopify_push_fiche_list(self, config, shopify_product_id):
        """Crée/met à jour un métaobjet "Fiche marketplace" par ligne
        (Fiche Amazon, Fiche Etsy) et les range dans le métachamp liste
        épinglé "Fiches marketplace" du produit Shopify."""
        self.ensure_one()
        contents = self.shopify_marketplace_content_ids.filtered(
            lambda c: c.marketplace_id.active
        ).sorted(lambda c: (c.marketplace_id.sequence, c.marketplace_id.id))
        product_gid = f"gid://shopify/Product/{shopify_product_id}"
        client = config.get_client()
        # 1) Liste déroulante « Fiche active » (indépendante des métaobjets).
        main_content = self._shopify_main_content()
        if main_content:
            try:
                config._shopify_ensure_fiche_choice_definition()
                config._shopify_graphql_checked(
                    """mutation($metafields: [MetafieldsSetInput!]!) {
                         metafieldsSet(metafields: $metafields) { userErrors { field message code } } }""",
                    {
                        "metafields": [
                            {
                                "ownerId": product_gid,
                                "namespace": config.FICHE_LIST_NAMESPACE,
                                "key": config.FICHE_ACTIVE_KEY,
                                "type": "single_line_text_field",
                                "value": config._shopify_fiche_label(main_content.marketplace_id),
                            }
                        ]
                    },
                    "metafieldsSet",
                )
            except ShopifyAPIError as exc:
                _logger.warning("« Fiche active » : échec pour %s : %s", self.display_name, exc)
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "out",
                        "model_name": "product.template",
                        "res_id": self.id,
                        "shopify_object_type": "fiche active",
                        "shopify_object_id": shopify_product_id,
                        "state": "error",
                        "message": str(exc),
                    }
                )
        # 2) Fiches détaillées (métaobjets, consultables via « Tout afficher »).
        try:
            config._shopify_ensure_fiche_list_definition()
            wanted = []
            for content in contents:
                handle = re.sub(r"[^a-z0-9-]+", "-", f"odoo-{self.id}-{content.marketplace_id.code}".lower())
                values = self._shopify_fiche_values(content)
                payload, _data = config._shopify_graphql_checked(
                    """
                    mutation($handle: MetaobjectHandleInput!, $metaobject: MetaobjectUpsertInput!) {
                      metaobjectUpsert(handle: $handle, metaobject: $metaobject) {
                        metaobject { id }
                        userErrors { field message code }
                      }
                    }""",
                    {
                        "handle": {"type": config.FICHE_METAOBJECT_TYPE, "handle": handle},
                        "metaobject": {
                            "fields": [{"key": k, "value": v} for k, v in values.items() if v != ""]
                        },
                    },
                    "metaobjectUpsert",
                )
                gid = (payload.get("metaobject") or {}).get("id")
                if gid:
                    wanted.append(gid)
                    if content.shopify_fiche_gid != gid:
                        content.with_context(shopify_sync=True).write({"shopify_fiche_gid": gid})
            # Fiches devenues obsolètes (ligne marketplace supprimée).
            data = client.graphql(
                """query($id: ID!) { product(id: $id) {
                     metafield(namespace: "%s", key: "%s") { id value } } }"""
                % (config.FICHE_LIST_NAMESPACE, config.FICHE_LIST_KEY),
                variables={"id": product_gid},
            )
            current = ((data or {}).get("product") or {}).get("metafield") or {}
            try:
                old_ids = json.loads(current.get("value") or "[]")
            except ValueError:
                old_ids = []
            if wanted:
                config._shopify_graphql_checked(
                    """
                    mutation($metafields: [MetafieldsSetInput!]!) {
                      metafieldsSet(metafields: $metafields) {
                        userErrors { field message code }
                      }
                    }""",
                    {
                        "metafields": [
                            {
                                "ownerId": product_gid,
                                "namespace": config.FICHE_LIST_NAMESPACE,
                                "key": config.FICHE_LIST_KEY,
                                "type": "list.metaobject_reference",
                                "value": json.dumps(wanted),
                            }
                        ]
                    },
                    "metafieldsSet",
                )
            elif current.get("id"):
                legacy_id = current["id"].rsplit("/", 1)[-1]
                client.rest_delete(f"/metafields/{legacy_id}.json")
            for old_id in set(old_ids) - set(wanted):
                config._shopify_graphql_checked(
                    """mutation($id: ID!) { metaobjectDelete(id: $id) {
                         deletedId userErrors { field message code } } }""",
                    {"id": old_id},
                    "metaobjectDelete",
                )
        except ShopifyAPIError as exc:
            _logger.warning("Liste « Fiches marketplace » : échec pour %s : %s", self.display_name, exc)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "fiches marketplace",
                    "shopify_object_id": shopify_product_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    def _shopify_set_fiche_active_metafield(self, config, shopify_product_id):
        main_content = self._shopify_main_content()
        if not main_content:
            return
        try:
            config._shopify_ensure_fiche_choice_definition()
            config._shopify_graphql_checked(
                """mutation($metafields: [MetafieldsSetInput!]!) {
                     metafieldsSet(metafields: $metafields) { userErrors { field message code } } }""",
                {
                    "metafields": [
                        {
                            "ownerId": f"gid://shopify/Product/{shopify_product_id}",
                            "namespace": config.FICHE_LIST_NAMESPACE,
                            "key": config.FICHE_ACTIVE_KEY,
                            "type": "single_line_text_field",
                            "value": config._shopify_fiche_label(main_content.marketplace_id),
                        }
                    ]
                },
                "metafieldsSet",
            )
        except ShopifyAPIError as exc:
            _logger.warning("« Fiche active » : échec pour %s : %s", self.display_name, exc)

    def _shopify_switch_fiche_now(self):
        """Changement de fiche : envoi RAPIDE immédiat (contenu principal),
        puis envoi complet (photos, métachamps...) en arrière-plan."""
        started = time.time()
        for template in self:
            template.with_context(shopify_sync=True, shopify_fast_push=True)._shopify_push_one()
            template._shopify_queue_push()
            for config in template.shopify_link_ids.config_id:
                self.env["shopify.sync.log"].sudo().create(
                    {
                        "config_id": config.id,
                        "direction": "out",
                        "model_name": "product.template",
                        "res_id": template.id,
                        "shopify_object_type": "fiche active",
                        "shopify_object_id": template._shopify_get_link(config).shopify_product_id,
                        "state": "success",
                        "message": _("Fiche « %(fiche)s » appliquée sur Shopify en %(sec).1f s (photos et détails en arrière-plan).")
                        % {"fiche": template._shopify_main_content().marketplace_id.name, "sec": time.time() - started},
                    }
                )

    def _shopify_queue_push(self, config=None):
        """Programme un renvoi vers Shopify en arrière-plan, exécuté tout de
        suite par la tâche « Shopify : renvois en attente ». Plusieurs
        demandes rapprochées = un seul renvoi (pas de chevauchement).
        `config` : boutique précise à viser (utile pour un produit pas
        encore lié, qui n'a donc aucune boutique dans shopify_link_ids)."""
        vals = {"shopify_push_pending": True}
        if config:
            vals["shopify_push_config_ids"] = [(4, cfg.id) for cfg in config]
        self.with_context(shopify_sync=True).write(vals)
        cron = self.env.ref("shopify_odoo_connector.cron_shopify_pending_push", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _cron_shopify_process_pending_push(self, limit=50):
        # 1) Changements de fiche venus de Shopify : envoi RAPIDE d'abord
        #    (titre, prix, variantes... visibles en ~1 s), pour TOUS.
        switching = self.sudo().search([("shopify_switch_pending", "=", True)], limit=limit)
        for template in switching:
            template.with_context(shopify_sync=True).write({"shopify_switch_pending": False})
            try:
                template._shopify_switch_fiche_now()
            except Exception:  # noqa: BLE001
                _logger.exception("Changement de fiche impossible pour %s", template.display_name)
            self.env.cr.commit()
        # 2) Envois complets (photos, métachamps, fiches détaillées).
        templates = self.sudo().search([("shopify_push_pending", "=", True)], limit=limit)
        default_config = self.env["shopify.config"].sudo()._shopify_default_config()
        for template in templates:
            configs = template.shopify_push_config_ids | template.shopify_link_ids.config_id
            if not configs and default_config and default_config.sync_products:
                configs = default_config
            template.with_context(shopify_sync=True).write(
                {"shopify_push_pending": False, "shopify_push_config_ids": [(5, 0, 0)]}
            )
            try:
                for config in configs:
                    template.with_context(shopify_sync=True, shopify_push_now=True)._shopify_push_one(
                        config=config
                    )
            except Exception:  # noqa: BLE001
                _logger.exception("Renvoi Shopify en attente impossible pour %s", template.display_name)
            self.env.cr.commit()  # chaque produit est enregistré dès qu'il est traité

    def _shopify_apply_active_fiche_from_shopify(self, config, shopify_product_id):
        """Webhook products/update : si le métachamp « Fiche active » a été
        changé dans Shopify (ex : Fiche Amazon -> Fiche Etsy), l'applique
        dans Odoo et renvoie le produit (titre / description / prix /
        photo / tags = fiche choisie). Renvoie True si un changement a été
        appliqué."""
        self.ensure_one()
        if not self.shopify_marketplace_content_ids:
            return False
        try:
            result = config.get_client().rest_get(
                f"/products/{shopify_product_id}/metafields.json",
                params={"namespace": config.FICHE_LIST_NAMESPACE},
            )
        except ShopifyAPIError:
            return False
        label = False
        for metafield in result.get("metafields") or []:
            if metafield.get("namespace") == config.FICHE_LIST_NAMESPACE and metafield.get("key") == config.FICHE_ACTIVE_KEY:
                label = (metafield.get("value") or "").strip()
        if not label:
            return False
        chosen_content = self.shopify_marketplace_content_ids.filtered(
            lambda c: config._shopify_fiche_label(c.marketplace_id) == label
        )[:1]
        if not chosen_content:
            # Fiche choisie absente sur CE produit dans Odoo (ex : Fiche
            # TikTok sans ligne TikTok) : on remet la fiche actuelle.
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "in",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "fiche active",
                    "shopify_object_id": str(shopify_product_id),
                    "state": "error",
                    "message": _("« %s » n'existe pas pour ce produit dans Odoo : choix ignoré.") % label,
                }
            )
            self._shopify_queue_push()
            return True
        chosen = chosen_content.marketplace_id
        current = self._shopify_main_content().marketplace_id
        if chosen == current:
            return False
        self.with_context(shopify_sync=True).write(
            {"shopify_active_marketplace_id": chosen.id, "shopify_switch_pending": True}
        )
        # Envoi RAPIDE (titre / prix / variantes) fait ICI, EN SYNCHRONE,
        # pendant le traitement du webhook : c'est justement la partie
        # "rapide" (un seul appel API, ~1 s), donc pas besoin d'attendre
        # le prochain passage du cron pour qu'elle parte. Le contenu est
        # donc à jour sur Shopify dès que le webhook a fini de répondre ;
        # il suffit de recharger la page produit dans Shopify Admin pour
        # le voir (Shopify ne rafraîchit jamais tout seul un onglet déjà
        # ouvert, quelle que soit la rapidité du renvoi).
        try:
            self.with_context(shopify_sync=True, shopify_fast_push=True)._shopify_push_one()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Envoi rapide (changement de fiche) impossible pour %s",
                self.display_name,
            )
        finally:
            self.with_context(shopify_sync=True).write({"shopify_switch_pending": False})
        # Envoi COMPLET (photos, métachamps, fiches détaillées) : celui-ci
        # reste en arrière-plan car il peut faire plusieurs appels API et
        # n'a pas besoin d'être instantané.
        self._shopify_queue_push()
        self.env["shopify.sync.log"].sudo().create(
            {
                "config_id": config.id,
                "direction": "in",
                "model_name": "product.template",
                "res_id": self.id,
                "shopify_object_type": "fiche active",
                "shopify_object_id": str(shopify_product_id),
                "state": "success",
                "message": _("Fiche active changée dans Shopify : %s") % label,
            }
        )
        return True

    def _shopify_has_etsy_fiche(self):
        """Vrai si la fiche ACTIVE (celle qui occupe les champs standards
        du produit Shopify en ce moment) est une fiche Etsy : c'est cette
        fiche qu'OrderBridge lit et pousse vers Etsy. Une fiche Etsy qui
        existe dans Odoo mais n'est PAS la fiche active (ex : Amazon
        actuellement actif) ne doit pas laisser le produit dans le filtre
        OrderBridge, sinon OrderBridge pousserait vers Etsy un produit qui
        affiche en réalité le contenu Amazon."""
        self.ensure_one()
        main = self._shopify_main_content()
        return bool(main and main.marketplace_id.platform_type == "etsy")

    def _shopify_sync_etsy_collection(self, config, shopify_product_id, _retry=True):
        """Ajoute le produit Shopify à la collection Etsy s'il a une fiche
        Etsy dans Odoo ; l'en retire sinon. OrderBridge filtré sur cette
        collection n'affiche donc QUE les produits à fiche Etsy."""
        self.ensure_one()
        has_etsy = self._shopify_has_etsy_fiche()
        try:
            collection_id = config._shopify_etsy_collection_id(create=has_etsy)
            if not collection_id:
                return
            client = config.get_client()
            existing = client.rest_get(
                "/collects.json",
                params={"product_id": shopify_product_id, "collection_id": collection_id},
            ).get("collects") or []
            if has_etsy and not existing:
                client.rest_post(
                    "/collects.json",
                    {"collect": {"product_id": int(shopify_product_id), "collection_id": int(collection_id)}},
                )
            elif not has_etsy:
                for collect in existing:
                    client.rest_delete(f"/collects/{collect['id']}.json")
        except ShopifyAPIError as exc:
            if _retry and exc.status_code in (404, 422) and has_etsy:
                # Collection supprimée à la main dans Shopify : on la recrée.
                config.sudo().write({"etsy_collection_id": False})
                return self._shopify_sync_etsy_collection(config, shopify_product_id, _retry=False)
            _logger.warning("Collection Etsy : échec pour %s : %s", self.display_name, exc)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "collection Etsy",
                    "shopify_object_id": shopify_product_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    def _shopify_main_content(self):
        """Fiche marketplace qui occupe les CHAMPS STANDARDS du produit
        Shopify unique (mode « shopify_main », ex : Etsy pour OrderBridge).
        Vide = comportement historique (fiche Odoo)."""
        self.ensure_one()
        active = self.shopify_active_marketplace_id
        if active:
            chosen = self.shopify_marketplace_content_ids.filtered(lambda c: c.marketplace_id == active)[:1]
            if chosen:
                return chosen
        lines = self.shopify_marketplace_content_ids.filtered(lambda c: c.marketplace_id.active)
        main = lines.filtered(lambda c: c.marketplace_id.shopify_publish_mode == "shopify_main")[:1]
        if main:
            return main
        # Pas de fiche Etsy / pas de choix : 1re fiche (ordre des
        # marketplaces), pour que « Fiche active » ne soit jamais vide.
        return lines.sorted(lambda c: (c.marketplace_id.sequence, c.marketplace_id.id))[:1]

    def _shopify_should_defer_push(self):
        """Vrai si on est dans une requête HTTP (interface web, webhook) et
        pas déjà dans la tâche de renvoi. L'envoi rapide de changement de
        fiche (une seule requête Shopify) reste immédiat."""
        ctx = self.env.context
        if ctx.get("shopify_push_now") or ctx.get("shopify_fast_push"):
            return False
        try:
            from odoo.http import request
            return bool(request)
        except Exception:  # noqa: BLE001
            return False

    def _shopify_push_one(self, config=None):
        """Pousse ce produit vers Shopify. Si `config` n'est pas fourni,
        pousse vers TOUTES les boutiques déjà liées à ce produit (un produit
        partagé entre plusieurs boutiques est mis à jour partout)."""
        self.ensure_one()
        if self._shopify_should_defer_push():
            # Enregistrement depuis l'interface : l'envoi complet (produit,
            # photos, métachamps, fiches, stock...) peut durer longtemps. Le
            # faire PENDANT la sauvegarde gardait la transaction ouverte
            # trop longtemps : PostgreSQL finissait par fermer la connexion
            # (« cursor already closed ») et la sauvegarde échouait. On le
            # fait donc en arrière-plan, déclenché immédiatement.
            self._shopify_queue_push(config)
            return
        if config is None:
            for cfg in self.shopify_link_ids.config_id:
                self._shopify_push_one(config=cfg)
            return
        if not self._shopify_matches_brand_filter(config):
            _logger.info(
                "Produit %s ignoré pour la boutique %s : case \"Afficher "
                "sur Shopify\"=%s, marque '%s' (inclure='%s', exclure='%s').",
                self.display_name,
                config.display_name,
                self.shopify_display,
                self.shopify_vendor or "",
                config.export_brand_filter,
                config.export_brand_exclude,
            )
            # S'il était déjà présent sur Shopify (ex: case décochée après
            # un premier envoi), on l'archive activement plutôt que de se
            # contenter de ne plus le mettre à jour.
            existing_link = self._shopify_get_link(config)
            if existing_link and existing_link.shopify_product_id:
                try:
                    config.get_client().rest_put(
                        f"/products/{existing_link.shopify_product_id}.json",
                        {"product": {"id": int(existing_link.shopify_product_id), "status": "archived"}},
                    )
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "Erreur archivage Shopify du produit %s suite à un "
                        "filtre/case décochée",
                        self.display_name,
                    )
                existing_link.unlink()
            return
        link = self._shopify_get_link(config)
        client = config.get_client()

        # Options (ex: Taille, Couleur) : indispensable pour que Shopify
        # affiche correctement les variantes du produit. Sans ce champ,
        # Shopify ne sait pas comment nommer/distinguer les variantes et
        # les envoie toutes sous une seule option "Title".
        option_lines = self._shopify_export_option_lines()

        # 1 produit Odoo (2 fiches) -> 1 produit Shopify : la fiche en mode
        # « champs standards » (Etsy) remplit title/body/prix/tags, lus par
        # OrderBridge ; les autres fiches (Amazon) partent en métachamps.
        main_content = self._shopify_main_content()
        variants_payload = []
        for v in self.product_variant_ids:
            variant_link = v._shopify_get_variant_link(config)
            price = (
                f"{main_content._shopify_main_variant_price(v):.2f}"
                if main_content
                else str(v.list_price)
            )
            variant_vals = {
                "id": (
                    int(variant_link.shopify_variant_id)
                    if variant_link and variant_link.shopify_variant_id
                    else None
                ),
                "price": price,
                "sku": (
                    (main_content._shopify_main_variant_sku(v) if main_content else "")
                    or v.default_code
                    or ""
                ),
                "barcode": v.barcode or "",
            }
            variant_vals.update(self._shopify_variant_weight_vals(v))
            if option_lines:
                option_values = self._shopify_variant_option_values(v, option_lines)
                for index, value in enumerate(option_values, start=1):
                    # Shopify exige une valeur non vide pour chaque option
                    # déclarée sur le produit ; à défaut on retombe sur le
                    # nom de la variante pour éviter un rejet de l'API.
                    variant_vals[f"option{index}"] = value or v.display_name
            variants_payload.append(variant_vals)

        # Titre / description : chaque boutique (lien) peut avoir sa propre
        # surcharge (ex : texte optimisé Amazon != texte optimisé Etsy),
        # sans jamais dupliquer le produit Odoo. À défaut de surcharge sur
        # CE lien, on retombe sur le nom/la description de la fiche
        # produit Odoo (comportement par défaut, inchangé).
        title = (link.shopify_title_override if link else False) or self.name
        description_html = (
            (link.shopify_description_override if link else False)
            or self.description
            or ""
        )
        if main_content:
            title = main_content.effective_title or title
            description_html = main_content.effective_description or description_html
        payload_product = {
            "title": title,
            "body_html": description_html,
            "vendor": self.shopify_vendor or "",
            "variants": variants_payload,
        }
        if main_content:
            # « Catégorie marketplace » de la fiche active : envoyée dans la
            # CATÉGORIE standard Shopify (taxonomie, via GraphQL, voir
            # _shopify_push_taxonomy_category), et non plus dans « Type ».
            # (La marque Shopify « vendor » n'est PAS changée : elle sert au
            # filtre de marque de la boutique ; la marque Amazon reste dans
            # le métachamp marketplace_amazon.brand.)
            payload_product["metafields_global_title_tag"] = (main_content.effective_title or title)[:70]
            seo_description = _shopify_html_to_text(main_content.effective_description or description_html)
            if seo_description:
                payload_product["metafields_global_description_tag"] = seo_description[:320]
            # Tags Shopify = tags de la fiche active (Etsy : tags Etsy,
            # poussés par OrderBridge ; Amazon : mots-clés Amazon).
            raw_tags = main_content.etsy_style_tags or main_content.amazon_search_terms or ""
            tags = [t.strip()[:20] for t in raw_tags.split(",") if t.strip()]
            payload_product["tags"] = ", ".join(tags[:13])
        if option_lines:
            payload_product["options"] = [
                {"name": line.attribute_id.name} for line in option_lines
            ]
        payload = {"product": payload_product}
        shopify_product_id = link.shopify_product_id if link else False
        try:
            if shopify_product_id:
                result = client.rest_put(
                    f"/products/{shopify_product_id}.json", payload
                )
            else:
                result = client.rest_post("/products.json", payload)
                new_id = result.get("product", {}).get("id")
                if new_id:
                    Link = self.env["shopify.product.link"].sudo()
                    if link:
                        link.write({"shopify_product_id": str(new_id)})
                    else:
                        link = Link.with_context(shopify_sync=True).create(
                            {
                                "product_tmpl_id": self.id,
                                "config_id": config.id,
                                "shopify_product_id": str(new_id),
                            }
                        )
                    shopify_product_id = str(new_id)
                    # Relier également les variantes fraîchement créées côté
                    # Shopify à leurs équivalents Odoo.
                    new_variants = result.get("product", {}).get("variants", []) or []
                    VariantLink = self.env["shopify.variant.link"].sudo()
                    for v, sv in zip(self.product_variant_ids, new_variants):
                        if not v._shopify_get_variant_link(config):
                            VariantLink.with_context(shopify_sync=True).create(
                                {
                                    "product_id": v.id,
                                    "config_id": config.id,
                                    "shopify_variant_id": str(sv.get("id")),
                                    "shopify_inventory_item_id": str(
                                        sv.get("inventory_item_id") or ""
                                    ),
                                }
                            )
            if shopify_product_id:
                # Liens de variantes réparés à CHAQUE envoi (POST et PUT) :
                # sans `shopify_inventory_item_id`, le stock ne peut jamais
                # être envoyé vers Shopify.
                self._shopify_refresh_variant_links(
                    config, result.get("product", {}).get("variants", []) or []
                )
            if shopify_product_id and main_content:
                self._shopify_push_taxonomy_category(config, shopify_product_id, main_content)
            if shopify_product_id and self.env.context.get("shopify_fast_push"):
                # ENVOI RAPIDE (changement de fiche) : le produit (titre,
                # description, prix, SKU, tags, type, SEO) est déjà à jour
                # grâce au PUT ci-dessus (≈ 1 s). On aligne juste la liste
                # « Fiche active » ; photos, métachamps et fiches détaillées
                # suivent dans un 2e envoi, en arrière-plan.
                self._shopify_set_fiche_active_metafield(config, shopify_product_id)
            elif shopify_product_id:
                # Les photos sont envoyées APRÈS la création/mise à jour du
                # produit lui-même : il faut son ID Shopify pour pouvoir
                # attacher des images dessus.
                self._shopify_push_images(config)
                # Différenciation Amazon/Etsy SANS dupliquer le produit :
                # chaque marketplace écrit son propre métachamp sur CE
                # même produit Shopify (1 produit Odoo = 1 produit
                # Shopify, toujours).
                # Fiche Amazon VISIBLE sur la page produit Shopify
                # (définitions de métachamps épinglées, créées une fois).
                try:
                    config._shopify_ensure_fiche_definitions()
                except ShopifyAPIError:
                    _logger.exception("Définitions de métachamps Shopify impossibles à créer")
                self._shopify_push_marketplace_metafields(config, shopify_product_id)
                # Produits Shopify DÉDIÉS (marketplaces en mode "produit
                # dédié", ex : Etsy via OrderBridge) : créés/mis à jour
                # ici ; ceux qui ne correspondent plus à aucune ligne en
                # mode dédié sont supprimés.
                self._shopify_sync_marketplace_dedicated_products(config)
                # Etsy en mode "API Etsy" : UN SEUL produit Shopify (contenu
                # Amazon) ; l'annonce Etsy reçoit son propre contenu
                # directement depuis Odoo.
                self._shopify_push_etsy_listings(config=config, shopify_product_id=shopify_product_id)
                # Collection "Etsy (OrderBridge)" : seuls les produits ayant
                # une fiche Etsy y figurent (filtre OrderBridge).
                self._shopify_sync_etsy_collection(config, shopify_product_id)
                # Liste "Fiches marketplace" (Fiche Amazon / Fiche Etsy),
                # cliquable sur la page produit Shopify.
                self._shopify_push_fiche_list(config, shopify_product_id)
                # Stock : envoyé aussi juste après la création/mise à jour du
                # produit. Avant, il ne partait QUE lors d'un mouvement de
                # stock ultérieur : un produit déjà en stock dans Odoo
                # arrivait donc à 0 sur Shopify.
                if config.sync_inventory:
                    self._shopify_push_main_stock(config)
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": shopify_product_id,
                    "state": "success",
                }
            )
        except ShopifyAPIError as exc:
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": shopify_product_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # Déclenchement automatique (temps réel) Odoo -> Shopify
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Déclenchement automatique (temps réel) Odoo -> Shopify
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "shopify_vendor" in vals and "shopify_display" not in vals:
                vals["shopify_display"] = self._shopify_display_for_vendor(vals.get("shopify_vendor"))
        templates = super().create(vals_list)
        if self.env.context.get("shopify_sync"):
            return templates

        default_config = self.env["shopify.config"]._shopify_default_config()
        for template in templates:
            if template.shopify_link_ids:
                # Produit créé avec des liens déjà fournis explicitement
                # (ex: import) : chaque lien gère lui-même son export.
                continue
            config = default_config
            if not config or not config.sync_products:
                continue
            # Un produit fraîchement créé n'a jamais encore d'ID Shopify :
            # _shopify_push_one() détecte cette absence et fait un POST
            # (création) plutôt qu'un PUT (mise à jour).
            template.with_context(shopify_sync=True)._shopify_push_one(config=config)
        return templates

    def _shopify_migrate_recompute_display(self):
        """Recalcule "Afficher sur Shopify" pour TOUS les produits déjà
        existants, à partir de leur marque actuelle (shopify_vendor).
        Nécessaire car le calcul automatique (onchange/create/write) ne
        s'applique qu'aux créations/modifications à venir : sans cette
        migration, les produits créés avant l'ajout de cette règle
        garderaient l'ancienne valeur (souvent "coché" par défaut, y
        compris pour des produits standards sans marque). Rejouée à
        chaque mise à jour du module (data function, voir
        data/shopify_display_migration.xml) : sans coût si déjà à jour.
        N'appelle PAS _shopify_push_one ici (pas d'appel réseau immédiat
        pour potentiellement des milliers de produits) : un produit ainsi
        démasqué sera archivé sur Shopify par la tâche planifiée
        (_shopify_enforce_brand_filter), à son rythme normal."""
        templates = self.sudo().search([])
        for template in templates:
            wanted = self._shopify_display_for_vendor(template.shopify_vendor)
            if template.shopify_display != wanted:
                template.with_context(shopify_sync=True).write({"shopify_display": wanted})

    def write(self, vals):
        if "shopify_vendor" in vals and "shopify_display" not in vals:
            vals = dict(vals, shopify_display=self._shopify_display_for_vendor(vals.get("shopify_vendor")))
        sync = not self.env.context.get("shopify_sync")
        # Détection AVANT l'écriture : un produit qu'on est en train
        # d'archiver (active True -> False) doit être supprimé côté
        # Shopify, comme une vraie suppression.
        to_delete_from_shopify = (
            self.filtered(lambda t: t.active) if sync and vals.get("active") is False else self.browse()
        )
        result = super().write(vals)
        if to_delete_from_shopify:
            to_delete_from_shopify._shopify_delete_all_shopify_products(
                "Produit archivé dans Odoo."
            )
        if not sync:
            return result
        trigger_fields = {
            "name",
            "list_price",
            "description",
            "shopify_vendor",
            "shopify_display",
            "image_1920",
            "product_template_image_ids",
            # Différenciation par marketplace (métachamps) : doit aussi
            # déclencher un renvoi si les lignes sont modifiées via le
            # formulaire produit complet (sauvegarde groupée). Une
            # modification faite directement sur une ligne (popup dédié)
            # est déjà couverte par shopify.product.marketplace.content.write().
            "shopify_marketplace_content_ids",
            "shopify_active_marketplace_id",
            # L'ajout/modification d'options (Taille, Couleur, ...) doit
            # aussi déclencher un renvoi vers Shopify, sinon les variantes
            # nouvellement créées dans Odoo n'apparaissent jamais côté
            # Shopify tant que personne ne clique manuellement sur
            # "Envoyer vers Shopify".
            "attribute_line_ids",
        }
        if set(vals.keys()) == {"shopify_active_marketplace_id"}:
            # Changement de fiche depuis Odoo : contenu envoyé tout de suite,
            # photos/détails juste après en arrière-plan.
            self.filtered("shopify_link_ids")._shopify_switch_fiche_now()
            return result
        if trigger_fields.intersection(vals.keys()):
            default_config = self.env["shopify.config"]._shopify_default_config()
            for template in self:
                configs = template.shopify_link_ids.filtered(
                    lambda l: l.config_id.sync_products
                ).mapped("config_id")
                if not configs and default_config and default_config.sync_products:
                    # Produit jamais lié à une boutique (créé directement
                    # dans Odoo) : on le pousse vers la boutique par défaut
                    # dès sa première modification pertinente (nom, prix,
                    # variantes, ...), comme le fait déjà create().
                    configs = default_config
                for config in configs:
                    template.with_context(shopify_sync=True)._shopify_push_one(config=config)
        return result

    def _shopify_delete_all_shopify_products(self, reason):
        """Supprime côté Shopify le produit "par défaut" (chaque boutique
        liée) ET chaque produit dédié par marketplace, pour `self`.
        Utilisé à la fois par unlink() (suppression réelle) et par
        write() quand un produit est archivé (voir plus bas) — une
        erreur API est journalisée mais ne bloque jamais l'opération
        Odoo en cours."""
        MPLink = self.env["shopify.marketplace.product.link"].sudo()
        for template in self:
            for link in template.shopify_link_ids:
                if not link.shopify_product_id:
                    continue
                try:
                    link.config_id.get_client().rest_delete(
                        f"/products/{link.shopify_product_id}.json"
                    )
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": link.config_id.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": template.id,
                            "shopify_object_type": "product",
                            "shopify_object_id": link.shopify_product_id,
                            "state": "success",
                            "message": reason,
                        }
                    )
                except ShopifyAPIError as exc:
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": link.config_id.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": template.id,
                            "shopify_object_type": "product",
                            "shopify_object_id": link.shopify_product_id,
                            "state": "error",
                            "message": f"Échec suppression Shopify ({reason}) : {exc}",
                        }
                    )
                finally:
                    # Le produit Odoo (archivé) peut continuer d'exister :
                    # on supprime le lien pour éviter qu'un futur envoi
                    # pointe vers cet ID Shopify (supprimé ou non).
                    link.unlink()
            mp_links = MPLink.search([("product_tmpl_id", "=", template.id)])
            for link in mp_links:
                if not link.shopify_product_id:
                    continue
                try:
                    link.config_id.get_client().rest_delete(
                        f"/products/{link.shopify_product_id}.json"
                    )
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": link.config_id.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": template.id,
                            "shopify_object_type": f"product ({link.marketplace_id.name})",
                            "shopify_object_id": link.shopify_product_id,
                            "state": "success",
                            "message": reason,
                        }
                    )
                except ShopifyAPIError as exc:
                    self.env["shopify.sync.log"].sudo().create(
                        {
                            "config_id": link.config_id.id,
                            "direction": "out",
                            "model_name": "product.template",
                            "res_id": template.id,
                            "shopify_object_type": f"product ({link.marketplace_id.name})",
                            "shopify_object_id": link.shopify_product_id,
                            "state": "error",
                            "message": f"Échec suppression Shopify ({reason}) : {exc}",
                        }
                    )
                finally:
                    link.unlink()

    # ------------------------------------------------------------------
    # SUPPRESSION : Odoo -> Shopify
    # ------------------------------------------------------------------
    def unlink(self):
        """Supprime aussi, côté Shopify, le produit "par défaut" (chaque
        boutique liée) ET chaque produit dédié par marketplace (Amazon,
        Etsy, ...), avant la suppression Odoo elle-même."""
        if not self.env.context.get("shopify_sync"):
            self._shopify_delete_all_shopify_products(
                "Produit supprimé (suppression côté Odoo)."
            )
        return super().unlink()
