# -*- coding: utf-8 -*-
""" Mise à jour d'un module déjà installé : le post_init_hook n'est exécuté
qu'à l'installation, on crée donc ici l'arborescence par entreprise et on
range les dossiers employés / projets existants. """
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.enhanced_document_management import \
        setup_document_hierarchy
    setup_document_hierarchy(env)
