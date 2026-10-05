# -*- coding: utf-8 -*-
"""Les commandes Shopify importées doivent arriver dans Odoo en tant que
commandes confirmées (et non en devis) : on réactive la confirmation
automatique sur toutes les boutiques existantes."""


def migrate(cr, version):
    cr.execute("UPDATE shopify_config SET auto_confirm_orders = TRUE")
