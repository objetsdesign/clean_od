# -*- coding: utf-8 -*-
import base64
import logging

import requests

from odoo import api, fields, models, _

from .shopify_api_client import ShopifyAPIError

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
        options = data.get("options", []) or []
        template_vals = {
            "name": data.get("title"),
            "sale_ok": True,
            "purchase_ok": True,
            "type": "consu",
            "is_storable": True,
        }
        # La marque ("vendor" côté Shopify) est toujours resynchronisée :
        # c'est elle qui permet de distinguer vos différentes marques
        # (ex: Clérieu) une fois les produits importés dans Odoo.
        vendor = (data.get("vendor") or "").strip()
        if vendor:
            template_vals["shopify_vendor"] = vendor
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
                    link.write({"shopify_main_image_id": str(main_image.get("id"))})

        # --- Galerie (images supplémentaires) ---
        ProductImage = self.env["product.image"].sudo()
        for extra_image in images_data[1:]:
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
                ProductImage.create(
                    {
                        "name": template.name,
                        "image_1920": content,
                        "product_tmpl_id": template.id,
                        "shopify_image_id": str(extra_image.get("id")),
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
                variant_link.write({"shopify_variant_image_id": image_id})

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify
    # ------------------------------------------------------------------
    def action_shopify_push(self):
        for template in self:
            for config in template.shopify_link_ids.config_id:
                template._shopify_push_one(config=config)

    def _shopify_push_one(self, config=None):
        """Pousse ce produit vers Shopify. Si `config` n'est pas fourni,
        pousse vers TOUTES les boutiques déjà liées à ce produit (un produit
        partagé entre plusieurs boutiques est mis à jour partout)."""
        self.ensure_one()
        if config is None:
            for cfg in self.shopify_link_ids.config_id:
                self._shopify_push_one(config=cfg)
            return
        link = self._shopify_get_link(config)
        client = config.get_client()
        payload = {
            "product": {
                "title": self.name,
                "vendor": self.shopify_vendor or "",
                "variants": [
                    {
                        "id": (
                            int(v._shopify_get_variant_link(config).shopify_variant_id)
                            if v._shopify_get_variant_link(config)
                            and v._shopify_get_variant_link(config).shopify_variant_id
                            else None
                        ),
                        "price": str(v.list_price),
                        "sku": v.default_code or "",
                        "barcode": v.barcode or "",
                    }
                    for v in self.product_variant_ids
                ],
            }
        }
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

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        trigger_fields = {"name", "list_price", "description_sale", "shopify_vendor"}
        if trigger_fields.intersection(vals.keys()):
            for template in self:
                for config in template.shopify_link_ids.filtered(
                    lambda l: l.config_id.sync_products
                ).mapped("config_id"):
                    template.with_context(shopify_sync=True)._shopify_push_one(config=config)
        return result
