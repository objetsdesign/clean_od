# -*- coding: utf-8 -*-
"""Supprime les anciennes tâches « Shopify : finalisation connexion (<boutique>) »
(une par boutique, qui tentaient de se désactiver elles-mêmes et restaient
bloquées ou tournaient en boucle). Les boutiques concernées sont marquées
« finalisation en attente » : la nouvelle tâche unique la refera une fois."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    old_crons = env["ir.cron"].with_context(active_test=False).search(
        [("name", "=like", "Shopify : finalisation connexion (%")]
    )
    Config = env["shopify.config"].with_context(active_test=False)
    for cron in old_crons:
        if cron.active:
            name = cron.name[len("Shopify : finalisation connexion ("):-1]
            Config.search([("name", "=", name), ("state", "=", "connected")]).write(
                {"shopify_post_oauth_pending": True}
            )
    cr.execute("SELECT ir_actions_server_id FROM ir_cron WHERE id IN %s", (tuple(old_crons.ids) or (0,),))
    action_ids = [r[0] for r in cr.fetchall()]
    if old_crons:
        cr.execute("DELETE FROM ir_cron WHERE id IN %s", (tuple(old_crons.ids),))
        cr.execute("DELETE FROM ir_act_server WHERE id IN %s", (tuple(action_ids),))
        _logger.info("%s ancienne(s) tâche(s) de finalisation Shopify supprimée(s)", len(old_crons))
