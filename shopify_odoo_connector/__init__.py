# -*- coding: utf-8 -*-
from . import models
from . import controllers


def post_init_hook(env):
    """Filet de sécurité pour une installation fraîche : le
    <function> de data/shopify_display_migration.xml fait déjà ce
    travail à chaque install/upgrade, mais on le rejoue ici aussi pour
    ne dépendre d'aucun ordre de chargement particulier."""
    env["product.template"]._shopify_migrate_recompute_display()
