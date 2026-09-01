# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ProductImage(models.Model):
    _inherit = "product.image"

    # NB : le champ `product_variant_id` (variante spécifique à laquelle
    # cette photo appartient) existe déjà nativement sur product.image,
    # défini par website_sale ("Extra Variant Media" sur la fiche de
    # chaque variante). Pas besoin de champ maison : on s'appuie dessus.
    shopify_image_id = fields.Char(string="ID image Shopify", copy=False, index=True)
    shopify_image_hash = fields.Char(
        string="Empreinte image Shopify",
        copy=False,
        help="Empreinte (MD5) de la dernière version de cette image envoyée vers Shopify.",
    )
    shopify_image_variant_ref = fields.Char(
        string="Variante Shopify liée (dernier envoi)",
        copy=False,
        help=(
            "ID de variante Shopify auquel cette photo était attachée lors "
            "du dernier envoi. Permet de détecter un changement de "
            "variante ciblée (product_variant_id modifié) même quand la "
            "photo elle-même n'a pas changé, pour forcer un nouvel envoi "
            "vers Shopify."
        ),
    )

    def _shopify_marketplace_image_url(self):
        """URL web Odoo de cette image, envoyée comme métachamp
        `image_url` (namespace `marketplace_<code>`) sur le produit
        Shopify pour une marketplace donnée. Comme pour le titre/la
        description (voir ShopifyProductMarketplaceContent), Shopify
        lui-même n'est pas modifié : c'est à l'intégration qui publie
        réellement sur la marketplace de récupérer cette URL et d'y
        associer son propre visuel."""
        self.ensure_one()
        if not self.id:
            return False
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not base_url:
            _logger.warning(
                "web.base.url n'est pas configuré : impossible de générer "
                "l'URL de l'image marketplace pour product.image %s.",
                self.id,
            )
            return False
        return f"{base_url}/web/image/product.image/{self.id}/image_1920"

    def unlink(self):
        # Si l'image supprimée avait déjà été poussée vers Shopify, on la
        # supprime aussi côté Shopify pour rester synchronisé (sauf si la
        # suppression vient elle-même d'une synchro entrante Shopify).
        if not self.env.context.get("shopify_sync"):
            for image in self:
                if not image.shopify_image_id:
                    continue
                # Une photo spécifique à une variante (product_variant_id
                # renseigné) n'a généralement PAS de product_tmpl_id direct
                # (voir website_sale.ProductImage.create) : on retombe sur
                # le modèle de la variante dans ce cas.
                template = image.product_tmpl_id or image.product_variant_id.product_tmpl_id
                if not template:
                    continue
                for link in template.shopify_link_ids:
                    template._shopify_delete_image(link.config_id, image.shopify_image_id)
        return super().unlink()
