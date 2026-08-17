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

    # NB : 'Asie' n'est volontairement PAS une valeur de ce champ. La
    # classification Asie est gérée par le modèle séparé sale.order.sky
    # (voir models/sale_order_sky.py) afin de ne jamais écrire de donnée
    # 'Asie' sur sale.order — utilisez le bouton "Classer en Asie".
    b2fa_activity_type = fields.Selection([
        ('b2b', 'B2B Classique'),
        ('fund', 'Fund Raising'),
    ], string="Activité (Suivi Devis & Commandes)", tracking=True, copy=False,
        help="Classez ce devis/commande : il est alors automatiquement créé/actualisé "
             "dans le tableau de bord 'Suivi Devis & Commandes' dès l'enregistrement, "
             "sans action supplémentaire. Laissez vide pour l'exclure. "
             "Pour l'activité Asie, utilisez plutôt le bouton 'Classer en Asie' : elle "
             "est suivie sur une fiche séparée (sale.order.sky) qui ne modifie jamais "
             "cette commande Ventes.")

    b2fa_quote_id = fields.Many2one(
        'b2fa.quote', string="Devis (Suivi Devis & Commandes)", copy=False, readonly=True)
    b2fa_order_id = fields.Many2one(
        'b2fa.order', string="Commande (Suivi Devis & Commandes)", copy=False, readonly=True)

    # Champ 100% calculé (non stocké) : simple lecture d'une éventuelle fiche
    # sale.order.sky existante, uniquement pour piloter l'affichage des
    # boutons du formulaire. Rien n'est jamais écrit sur sale.order pour ça.
    b2fa_sky_id = fields.Many2one(
        'sale.order.sky', string="Fiche Asie", compute='_compute_b2fa_sky_id',
        search='_search_b2fa_sky_id',
        help="Fiche de classification 'Asie' liée à ce devis/commande, si elle existe.")

    @api.depends()
    def _compute_b2fa_sky_id(self):
        skies = self.env['sale.order.sky'].search([('sale_order_id', 'in', self.ids)])
        sky_by_order = {sky.sale_order_id.id: sky for sky in skies}
        for rec in self:
            rec.b2fa_sky_id = sky_by_order.get(rec.id, False)

    def _search_b2fa_sky_id(self, operator, value):
        """Minimal search support for b2fa_sky_id (non-stored), covering the
        two cases actually used by the UI: filtering on 'has'/'has no' linked
        Asie sheet ('!=' False / '=' False)."""
        classified_ids = self.env['sale.order.sky'].search([]).mapped('sale_order_id').ids
        if operator in ('=', '!=') and value is False:
            return [('id', 'not in' if operator == '=' else 'in', classified_ids)]
        return [('id', 'in', classified_ids)]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._b2fa_trigger_autosync()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('b2fa_no_autosync') and _B2FA_AUTOSYNC_TRIGGER_FIELDS & set(vals.keys()):
            self._b2fa_trigger_autosync()
            self._b2fa_trigger_sky_autosync()
        return res

    def _b2fa_trigger_autosync(self):
        """Push classified records into the Suivi Devis & Commandes app right away,
        so the dashboard reflects Ventes immediately — no manual sync, no waiting
        for the hourly safety-net cron."""
        to_sync = self.filtered(lambda r: r.b2fa_activity_type)
        if to_sync:
            self.env['b2fa.sale.sync'].run_sync(sale_orders=to_sync)

    def _b2fa_trigger_sky_autosync(self):
        """Si une de ces commandes Ventes est déjà classée 'Asie' (fiche
        sale.order.sky existante), réactualise cette fiche — sans jamais
        écrire sur sale.order lui-même."""
        skies = self.env['sale.order.sky'].search([('sale_order_id', 'in', self.ids)])
        if skies:
            self.env['b2fa.sale.sync'].run_sync_sky(sky_records=skies)

    def action_b2fa_sync_now(self):
        """Manual, single-record sync trigger from the sale.order form (kept as
        a convenience button, e.g. after a bulk import that bypassed write())."""
        self.env['b2fa.sale.sync'].run_sync(sale_orders=self)
        self._b2fa_trigger_sky_autosync()
        return True

    def action_b2fa_mark_asie(self):
        """Classe la/les commande(s) Ventes sélectionnée(s) comme 'Asie'.

        N'écrit JAMAIS sur sale.order : crée (ou retrouve) une fiche
        sale.order.sky par commande, ce qui déclenche aussitôt sa remontée
        dans le tableau de bord Asie."""
        Sky = self.env['sale.order.sky']
        existing = Sky.search([('sale_order_id', 'in', self.ids)])
        already_done_ids = set(existing.mapped('sale_order_id.id'))
        to_create = self.filtered(lambda r: r.id not in already_done_ids)

        new_skies = Sky
        if to_create:
            new_skies = Sky.create([{'sale_order_id': r.id} for r in to_create])
        if existing:
            existing._b2fa_trigger_autosync()

        all_skies = existing | new_skies
        if len(self) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': "Fiche Asie",
                'res_model': 'sale.order.sky',
                'view_mode': 'form',
                'res_id': all_skies[:1].id,
            }
        return True

    def action_b2fa_open_sky(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Fiche Asie",
            'res_model': 'sale.order.sky',
            'view_mode': 'form',
            'res_id': self.b2fa_sky_id.id,
        }
