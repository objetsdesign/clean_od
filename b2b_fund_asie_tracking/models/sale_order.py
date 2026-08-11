# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Fields whose change should re-trigger an automatic sync for records that are
# already classified (b2fa_activity_type set) — covers the info actually pushed
# into b2fa.quote / b2fa.order (client, dates, amount, status, lines...).
_B2FA_AUTOSYNC_TRIGGER_FIELDS = {
    'b2fa_activity_type', 'state', 'partner_id', 'date_order',
    'order_line', 'amount_total', 'amount_untaxed',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    b2fa_activity_type = fields.Selection([
        ('b2b', 'B2B Classique'),
        ('fund', 'Fund Raising'),
        ('asie', 'Asie'),
    ], string="Activité (Suivi Devis & Commandes)", tracking=True, copy=False,
        help="Classez ce devis/commande : il est alors automatiquement créé/actualisé "
             "dans le tableau de bord 'Suivi Devis & Commandes' dès l'enregistrement, "
             "sans action supplémentaire. Laissez vide pour l'exclure.")

    b2fa_quote_id = fields.Many2one(
        'b2fa.quote', string="Devis (Suivi Devis & Commandes)", copy=False, readonly=True)
    b2fa_order_id = fields.Many2one(
        'b2fa.order', string="Commande (Suivi Devis & Commandes)", copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._b2fa_trigger_autosync()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('b2fa_no_autosync') and _B2FA_AUTOSYNC_TRIGGER_FIELDS & set(vals.keys()):
            self._b2fa_trigger_autosync()
        return res

    def _b2fa_trigger_autosync(self):
        """Push classified records into the Suivi Devis & Commandes app right away,
        so the dashboard reflects Ventes immediately — no manual sync, no waiting
        for the hourly safety-net cron."""
        to_sync = self.filtered(lambda r: r.b2fa_activity_type)
        if to_sync:
            self.env['b2fa.sale.sync'].run_sync(sale_orders=to_sync)

    def action_b2fa_sync_now(self):
        """Manual, single-record sync trigger from the sale.order form (kept as
        a convenience button, e.g. after a bulk import that bypassed write())."""
        self.env['b2fa.sale.sync'].run_sync(sale_orders=self)
        return True
