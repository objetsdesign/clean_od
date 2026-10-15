# -*- coding: utf-8 -*-
"""shopify_fulfillment_status passe d'un champ texte libre à une liste de
choix. On normalise les anciennes valeurs (dont « success » écrit à tort
par le webhook des expéditions) avant la mise à jour du champ."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'sale_order'
           AND column_name = 'shopify_fulfillment_status'
        """
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE sale_order
           SET shopify_fulfillment_status = 'fulfilled'
         WHERE shopify_fulfillment_status IN ('success', 'fulfilled', 'shipped')
        """
    )
    cr.execute(
        """
        UPDATE sale_order
           SET shopify_fulfillment_status = 'unfulfilled'
         WHERE shopify_order_id IS NOT NULL
           AND (shopify_fulfillment_status IS NULL
                OR shopify_fulfillment_status NOT IN
                   ('unfulfilled', 'partial', 'fulfilled', 'restocked'))
        """
    )
