# -*- coding: utf-8 -*-
"""v9.39 : supprime les erreurs en double du journal (même variante, même
message), en gardant la plus récente."""


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM shopify_sync_log l
         USING shopify_sync_log k
         WHERE l.state = 'error'
           AND k.state = 'error'
           AND l.shopify_object_type = 'variant'
           AND k.shopify_object_type = 'variant'
           AND l.config_id IS NOT DISTINCT FROM k.config_id
           AND l.shopify_object_id IS NOT DISTINCT FROM k.shopify_object_id
           AND l.message IS NOT DISTINCT FROM k.message
           AND l.id < k.id
        """
    )
