# -*- coding: utf-8 -*-
from odoo import fields, models


class B2faSyncWizard(models.TransientModel):
    _name = 'b2fa.sync.wizard'
    _description = "Synchroniser depuis Ventes"

    activities = fields.Selection([
        ('all', 'Toutes les activités classées'),
        ('b2b', 'B2B Classique uniquement'),
        ('fund', 'Fund Raising uniquement'),
        ('asie', 'Asie uniquement'),
    ], string="Périmètre", default='all', required=True)
    result_log = fields.Text(string="Résultat de la synchronisation", readonly=True)

    def action_sync(self):
        self.ensure_one()

        # 'Asie' n'est jamais stockée sur sale.order : elle est synchronisée
        # séparément depuis sale.order.sky (run_sync_sky), jamais via
        # b2fa.sale.sync.run_sync (qui ne lit que b2fa_activity_type).
        stats_keys = ('quotes_created', 'quotes_updated', 'orders_created', 'orders_updated')
        stats = dict.fromkeys(stats_keys, 0)
        stats.update({'skipped_unclassified': 0, 'unclassified_total': 0})

        if self.activities in ('all', 'b2b', 'fund'):
            activities = None if self.activities == 'all' else [self.activities]
            so_stats = self.env['b2fa.sale.sync'].run_sync(activities=activities)
            for key in stats_keys:
                stats[key] += so_stats[key]
            stats['unclassified_total'] = so_stats['unclassified_total']

        if self.activities in ('all', 'asie'):
            sky_stats = self.env['b2fa.sale.sync'].run_sync_sky()
            for key in stats_keys:
                stats[key] += sky_stats[key]

        lines = [
            "Synchronisation terminée.",
            "",
            "Devis créés : %s" % stats['quotes_created'],
            "Devis mis à jour : %s" % stats['quotes_updated'],
            "Commandes créées : %s" % stats['orders_created'],
            "Commandes mises à jour : %s" % stats['orders_updated'],
        ]
        if stats['unclassified_total']:
            lines += [
                "",
                "⚠ %s devis/commandes du module Ventes n'ont pas d'activité "
                "(B2B / Fund Raising) assignée et ont donc été ignorés." % stats['unclassified_total'],
                "Ouvrez Ventes > Commandes, sélectionnez les lignes concernées et "
                "renseignez la colonne 'Activité (Suivi Devis & Commandes)' (vous pouvez "
                "modifier plusieurs lignes sélectionnées en une fois). Pour l'Asie, utilisez "
                "le bouton 'Classer en Asie' (aucun champ à renseigner sur la commande).",
            ]
        self.result_log = "\n".join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'b2fa.sync.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
