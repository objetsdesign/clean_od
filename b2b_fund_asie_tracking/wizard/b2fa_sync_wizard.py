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
        activities = None if self.activities == 'all' else [self.activities]
        stats = self.env['b2fa.sale.sync'].run_sync(activities=activities)

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
                "(B2B / Fund Raising / Asie) assignée et ont donc été ignorés." % stats['unclassified_total'],
                "Ouvrez Ventes > Commandes, sélectionnez les lignes concernées et "
                "renseignez la colonne 'Activité (Suivi Devis & Commandes)' (vous pouvez "
                "modifier plusieurs lignes sélectionnées en une fois).",
            ]
        self.result_log = "\n".join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'b2fa.sync.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
