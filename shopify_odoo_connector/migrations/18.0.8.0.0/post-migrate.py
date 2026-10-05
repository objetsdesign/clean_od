# -*- coding: utf-8 -*-
"""Commande Shopify = commande Odoo : la confirmation automatique est
obligatoire sur toutes les boutiques."""


def migrate(cr, version):
    cr.execute("UPDATE shopify_config SET auto_confirm_orders = TRUE")
