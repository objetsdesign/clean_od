# -*- coding: utf-8 -*-
"""« Afficher sur Shopify » devient le résultat du choix des boutiques :
on garde la liste des produits qui étaient cochés avant la mise à jour."""


def migrate(cr, version):
    cr.execute("DROP TABLE IF EXISTS shopify_display_backup")
    cr.execute(
        """
        CREATE TABLE shopify_display_backup AS
        SELECT id FROM product_template WHERE shopify_display IS TRUE
        """
    )
