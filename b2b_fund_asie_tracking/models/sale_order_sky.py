# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrderSky(models.Model):
    """Classification 'Asie' d'un devis/commande Ventes.

    Ce modèle est volontairement séparé de sale.order : le lien se fait
    UNIQUEMENT depuis sale.order.sky vers sale.order (Many2one ci-dessous),
    jamais dans l'autre sens. Odoo n'ajoute donc aucune colonne, aucun champ
    stocké et aucune donnée 'Asie' sur le modèle natif sale.order — la
    commande Ventes n'est jamais écrite/modifiée par cette classification.
    """
    _name = 'sale.order.sky'
    _description = "Classification Asie (Suivi Devis & Commandes) — externe à sale.order"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    sale_order_id = fields.Many2one(
        'sale.order', string="Devis/Commande Ventes", required=True, ondelete='cascade',
        index=True, tracking=True, copy=False,
        help="Devis/commande du module Ventes classé 'Asie'. Ce champ ne vit que sur "
             "cette fiche : sélectionner un devis/commande ici ne modifie jamais "
             "l'enregistrement sale.order correspondant.")

    display_name = fields.Char(compute='_compute_display_name', store=True)

    # Champs lus (related) depuis sale.order pour affichage/recherche pratiques :
    # une field related en lecture ne modifie jamais l'enregistrement source.
    partner_id = fields.Many2one(related='sale_order_id.partner_id', string="Client", store=True, readonly=True)
    date_order = fields.Datetime(related='sale_order_id.date_order', string="Date Ventes", store=True, readonly=True)
    currency_id = fields.Many2one(related='sale_order_id.currency_id', readonly=True)
    amount_total = fields.Monetary(related='sale_order_id.amount_total', string="Montant TTC", readonly=True)
    amount_untaxed = fields.Monetary(related='sale_order_id.amount_untaxed', string="Montant HT", readonly=True)
    sale_state = fields.Selection(related='sale_order_id.state', string="Statut Ventes", readonly=True)

    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    b2fa_quote_id = fields.Many2one('b2fa.quote', string="Devis (Suivi Devis & Commandes)",
                                     copy=False, readonly=True)
    b2fa_order_id = fields.Many2one('b2fa.order', string="Commande (Suivi Devis & Commandes)",
                                     copy=False, readonly=True)

    _sql_constraints = [
        ('sale_order_uniq', 'unique(sale_order_id)',
         "Ce devis/commande Ventes est déjà classé 'Asie'."),
    ]

    @api.depends('sale_order_id', 'sale_order_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.sale_order_id.name or "Nouveau"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._b2fa_trigger_autosync()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('b2fa_no_autosync'):
            self._b2fa_trigger_autosync()
        return res

    def _b2fa_trigger_autosync(self):
        """Pousse la fiche vers le tableau de bord Asie (b2fa.quote / b2fa.order),
        sans jamais lire ni écrire sur le modèle sale.order lui-même."""
        if self:
            self.env['b2fa.sale.sync'].run_sync_sky(sky_records=self)

    def action_b2fa_sync_now(self):
        self._b2fa_trigger_autosync()
        return True

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.sale_order_id.name,
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }
