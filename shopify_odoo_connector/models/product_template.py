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

    shopify_config_id = fields.Many2one("shopify.config", string="Boutique Shopify")
    shopify_product_id = fields.Char(string="ID produit Shopify", copy=False, index=True)
    shopify_handle = fields.Char(string="Handle Shopify")
    shopify_last_sync = fields.Datetime(string="Dernière synchro Shopify")
    shopify_sync_pending = fields.Boolean(default=False, copy=False)
    shopify_main_image_id = fields.Char(
        string="ID image principale Shopify", copy=False,
        help="Sert à ne retélécharger l'image principale que si elle a changé côté Shopify.",
    )

    _sql_constraints = [
        (
            "shopify_product_uniq",
            "unique(shopify_product_id, shopify_config_id)",
            "Ce produit Shopify est déjà importé.",
        ),
    ]

    # ------------------------------------------------------------------
    # IMPORT : Shopify -> Odoo
    # ------------------------------------------------------------------
    def shopify_import_all(self, config):
        """Importe tous les produits de la boutique Shopify `config`."""
        client = config.get_client()
        products = client.rest_get_with_pagination(
            "/products.json", params={"limit": 250}
        )
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

    def _shopify_create_or_update_from_data(self, data, config):
        Template = self.env["product.template"].sudo()
        template = Template.search(
            [
                ("shopify_product_id", "=", str(data["id"])),
                ("shopify_config_id", "=", config.id),
            ],
            limit=1,
        )
        options = data.get("options", []) or []
        vals = {
            "name": data.get("title"),
            "shopify_product_id": str(data["id"]),
            "shopify_handle": data.get("handle"),
            "shopify_config_id": config.id,
            "shopify_last_sync": fields.Datetime.now(),
            "sale_ok": True,
            "purchase_ok": True,
            "type": "consu",
            "is_storable": True,
        }
        ctx_self = self.with_context(shopify_sync=True)
        if template:
            # On ne touche pas aux attribute_line_ids d'un produit déjà importé
            # pour éviter d'écraser une configuration existante ; seule la
            # création initiale met en place les attributs/variantes.
            template.with_context(shopify_sync=True).write(vals)
        else:
            attribute_lines = self._shopify_prepare_attribute_lines(options)
            if attribute_lines:
                vals["attribute_line_ids"] = attribute_lines
            template = ctx_self.create(vals)

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
            }
        )
        return template

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
        Variant = self.env["product.product"].sudo()
        simple_product = self._shopify_is_simple_product(options)
        for variant_data in variants_data:
            variant = Variant.search(
                [
                    ("shopify_variant_id", "=", str(variant_data["id"])),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
            vals = {
                "shopify_variant_id": str(variant_data["id"]),
                "shopify_inventory_item_id": str(variant_data.get("inventory_item_id") or ""),
                "shopify_config_id": config.id,
                "default_code": variant_data.get("sku") or False,
                "barcode": variant_data.get("barcode") or False,
                "list_price": float(variant_data.get("price") or 0.0),
            }
            if variant:
                variant.with_context(shopify_sync=True).write(vals)
                continue

            if simple_product:
                # Produit sans option réelle : une seule variante par défaut,
                # déjà créée automatiquement par Odoo à la création du template.
                default_variant = template.product_variant_ids[:1]
                if default_variant and not default_variant.shopify_variant_id:
                    default_variant.with_context(shopify_sync=True).write(vals)
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
                matched.with_context(shopify_sync=True).write(vals)
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
        main_image = images_data[0]
        if str(main_image.get("id")) != template.shopify_main_image_id:
            content = self._shopify_download_image_base64(main_image.get("src"))
            if content:
                template.with_context(shopify_sync=True).write(
                    {
                        "image_1920": content,
                        "shopify_main_image_id": str(main_image.get("id")),
                    }
                )

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
        Variant = self.env["product.product"].sudo()
        for variant_data in variants_data:
            image_id = variant_data.get("image_id")
            if not image_id:
                continue
            image_id = str(image_id)
            variant_image = images_by_id.get(image_id)
            if not variant_image:
                continue
            variant = Variant.search(
                [
                    ("shopify_variant_id", "=", str(variant_data["id"])),
                    ("shopify_config_id", "=", config.id),
                ],
                limit=1,
            )
            if not variant or variant.shopify_variant_image_id == image_id:
                continue
            content = self._shopify_download_image_base64(variant_image.get("src"))
            if content:
                variant.with_context(shopify_sync=True).write(
                    {
                        "image_variant_1920": content,
                        "shopify_variant_image_id": image_id,
                    }
                )

    # ------------------------------------------------------------------
    # EXPORT : Odoo -> Shopify
    # ------------------------------------------------------------------
    def action_shopify_push(self):
        for template in self:
            if not template.shopify_config_id:
                continue
            template._shopify_push_one()

    def _shopify_push_one(self):
        self.ensure_one()
        config = self.shopify_config_id
        client = config.get_client()
        payload = {
            "product": {
                "title": self.name,
                "variants": [
                    {
                        "id": int(v.shopify_variant_id) if v.shopify_variant_id else None,
                        "price": str(v.list_price),
                        "sku": v.default_code or "",
                        "barcode": v.barcode or "",
                    }
                    for v in self.product_variant_ids
                ],
            }
        }
        try:
            if self.shopify_product_id:
                result = client.rest_put(
                    f"/products/{self.shopify_product_id}.json", payload
                )
            else:
                result = client.rest_post("/products.json", payload)
                new_id = result.get("product", {}).get("id")
                if new_id:
                    self.with_context(shopify_sync=True).write(
                        {"shopify_product_id": str(new_id), "shopify_config_id": config.id}
                    )
            self.env["shopify.sync.log"].sudo().create(
                {
                    "config_id": config.id,
                    "direction": "out",
                    "model_name": "product.template",
                    "res_id": self.id,
                    "shopify_object_type": "product",
                    "shopify_object_id": self.shopify_product_id,
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
                    "shopify_object_id": self.shopify_product_id,
                    "state": "error",
                    "message": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # Déclenchement automatique (temps réel) Odoo -> Shopify
    # ------------------------------------------------------------------
    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("shopify_sync"):
            return result
        trigger_fields = {"name", "list_price", "description_sale"}
        if trigger_fields.intersection(vals.keys()):
            for template in self:
                if template.shopify_config_id and template.shopify_config_id.sync_products:
                    template.with_context(shopify_sync=True)._shopify_push_one()
        return result
