# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductImage(models.Model):
    _inherit = "product.image"

    # Si renseigné, cette photo de la galerie "Média Ecommerce" n'est
    # rattachée qu'À CETTE variante (au lieu d'être commune à toutes les
    # variantes, comportement standard Odoo). Elle est alors envoyée vers
    # Shopify avec le variant_ids correspondant, ce qui fait qu'elle ne
    # s'affiche que pour cette variante côté Shopify également.
    product_id = fields.Many2one(
        "product.product",
        string="Variante spécifique",
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help=(
            "Laissez vide pour une photo commune à toutes les variantes "
            "(comportement standard Odoo). Choisissez une variante pour "
            "que cette photo n'apparaisse QUE pour elle, aussi bien dans "
            "Odoo que côté Shopify."
        ),
    )
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
            "variante ciblée (champ 'Variante spécifique' modifié) même "
            "quand la photo elle-même n'a pas changé, pour forcer un "
            "nouvel envoi vers Shopify."
        ),
    )

    def unlink(self):
        # Si l'image supprimée avait déjà été poussée vers Shopify, on la
        # supprime aussi côté Shopify pour rester synchronisé (sauf si la
        # suppression vient elle-même d'une synchro entrante Shopify).
        if not self.env.context.get("shopify_sync"):
            for image in self:
                if not image.shopify_image_id or not image.product_tmpl_id:
                    continue
                for link in image.product_tmpl_id.shopify_link_ids:
                    image.product_tmpl_id._shopify_delete_image(link.config_id, image.shopify_image_id)
        return super().unlink()
