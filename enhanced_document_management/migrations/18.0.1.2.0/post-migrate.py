# -*- coding: utf-8 -*-
""" 18.0.1.2.0 : ajoute le dossier « Meridian » dans l'arborescence de chaque
entreprise déjà existante (l'opération est idempotente). """
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.enhanced_document_management import \
        setup_document_hierarchy
    setup_document_hierarchy(env)
