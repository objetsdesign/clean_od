# -*- coding: utf-8 -*-
"""Le GTIN global de la fiche marketplace (amazon_gtin) est supprimé :
le GTIN / EAN / UPC se saisit désormais par variante (onglet Variantes).

Pour ne pas perdre les codes déjà saisis, on recopie amazon_gtin sur la
ligne variante lorsque la fiche n'a qu'UNE seule variante et que son GTIN
est vide (un même GTIN ne peut pas s'appliquer à plusieurs variantes).
La colonne est ensuite supprimée."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'shopify_product_marketplace_content'
           AND column_name = 'amazon_gtin'
        """
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE shopify_product_marketplace_variant v
           SET gtin_override = TRIM(c.amazon_gtin)
          FROM shopify_product_marketplace_content c
         WHERE v.content_id = c.id
           AND COALESCE(TRIM(c.amazon_gtin), '') <> ''
           AND COALESCE(TRIM(v.gtin_override), '') = ''
           AND (SELECT COUNT(*) FROM shopify_product_marketplace_variant v2
                 WHERE v2.content_id = c.id) = 1
        """
    )
    cr.execute("ALTER TABLE shopify_product_marketplace_content DROP COLUMN amazon_gtin")
