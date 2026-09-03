# -*- coding: utf-8 -*-
import base64
import hashlib
import logging

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
    shopify_marketplace_content_ids = fields.One2many(
        "shopify.product.marketplace.content",
        "product_tmpl_id",
        string="Contenu par marketplace",
    )

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
        if link:
            template = link.product_tmpl_id
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

        self._shopify_sync_variants(template, data.get("variants", []), config, options)
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
              productTaxonomyNode {
                id
                fullName
              }
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
        # Le champ "category" d'un produit Shopify ne porte pas directement
        # id/fullName : il faut passer par le sous-objet productTaxonomyNode
        # (voir doc Shopify : ProductCategory.productTaxonomyNode).
        shopify_category = category.get("productTaxonomyNode")
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
        """Envoie/actualise l'image principale (image_1920) vers Shopify."""
        self.ensure_one()
        if not self.image_1920 or not link or not link.shopify_product_id:
            return
        content_hash = self._shopify_hash(self.image_1920)
        if content_hash and content_hash == link.shopify_main_image_hash:
            return  # image inchangée depuis le dernier envoi : rien à faire
        client = config.get_client()
        payload = {"image": {"attachment": self.image_1920.decode()}}
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

    def _shopify_push_gallery_images(self, config, link):
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
            description_value = content.description_override or _shopify_html_to_text(self.description)
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
        except ShopifyAPIError:
            _logger.exception(
                "Impossible de lire les métachamps Shopify existants du produit %s",
                self.display_name,
            )
            return
        existing_map = {
            (mf.get("namespace"), mf.get("key")): mf.get("id")
            for mf in (existing.get("metafields") or [])
        }
        wanted_keys = set()
        for namespace, key, value, mtype in specs:
            wanted_keys.add((namespace, key))
            payload = {
                "metafield": {
                    "namespace": namespace,
                    "key": key,
                    "value": value,
                    "type": mtype,
                }
            }
            existing_id = existing_map.get((namespace, key))
            try:
                if existing_id:
                    client.rest_put(f"/metafields/{existing_id}.json", payload)
                else:
                    client.rest_post(f"/products/{shopify_product_id}/metafields.json", payload)
            except ShopifyAPIError:
                _logger.exception(
                    "Erreur envoi métachamp Shopify %s.%s pour le produit %s",
                    namespace, key, self.display_name,
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

    def _shopify_push_one(self, config=None):
        """Pousse ce produit vers Shopify. Si `config` n'est pas fourni,
        pousse vers TOUTES les boutiques déjà liées à ce produit (un produit
        partagé entre plusieurs boutiques est mis à jour partout)."""
        self.ensure_one()
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

        variants_payload = []
        for v in self.product_variant_ids:
            variant_link = v._shopify_get_variant_link(config)
            variant_vals = {
                "id": (
                    int(variant_link.shopify_variant_id)
                    if variant_link and variant_link.shopify_variant_id
                    else None
                ),
                "price": str(v.list_price),
                "sku": v.default_code or "",
                "barcode": v.barcode or "",
            }
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
        payload_product = {
            "title": title,
            "body_html": description_html,
            "vendor": self.shopify_vendor or "",
            "variants": variants_payload,
        }
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
                # Les photos sont envoyées APRÈS la création/mise à jour du
                # produit lui-même : il faut son ID Shopify pour pouvoir
                # attacher des images dessus.
                self._shopify_push_images(config)
                # Idem pour les métachamps Amazon/Etsy : nécessitent aussi
                # l'ID Shopify du produit.
                self._shopify_push_marketplace_metafields(config, shopify_product_id)
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
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
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
            # L'ajout/modification d'options (Taille, Couleur, ...) doit
            # aussi déclencher un renvoi vers Shopify, sinon les variantes
            # nouvellement créées dans Odoo n'apparaissent jamais côté
            # Shopify tant que personne ne clique manuellement sur
            # "Envoyer vers Shopify".
            "attribute_line_ids",
        }
        if trigger_fields.intersection(vals.keys()):
            # Répercute d'abord (titre, description, prix, stock, image,
            # galerie) sur les lignes marketplace qui suivent encore
            # automatiquement ce produit (voir
            # `_shopify_marketplace_sync_from_product` /
            # `auto_sync_with_product`), AVANT le renvoi vers Shopify
            # ci-dessous : les métachamps poussés reflètent alors déjà
            # les nouvelles valeurs.
            marketplace_sync_fields = {
                "name",
                "list_price",
                "description",
                "image_1920",
                "product_template_image_ids",
            }
            if marketplace_sync_fields.intersection(vals.keys()):
                for template in self:
                    template.shopify_marketplace_content_ids._shopify_marketplace_sync_from_product()
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
