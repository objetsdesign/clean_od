# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2faQuote(models.Model):
    _name = 'b2fa.quote'
    _description = "Devis (B2B / Fund Raising / Asie)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_devis desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string="N° Devis", required=True, copy=False, tracking=True,
        default=lambda self: "Nouveau",
        help="Format conseillé : DEV-AAAA-NNN (ex: DEV-2026-001)")

    activity_type = fields.Selection([
        ('b2b', 'B2B Classique'),
        ('fund', 'Fund Raising'),
        ('asie', 'Asie'),
    ], string="Activité", required=True, default='b2b', tracking=True)

    date_devis = fields.Date(string="Date Devis", default=fields.Date.context_today, tracking=True)
    client = fields.Char(string="Client", required=True, tracking=True)
    secteur = fields.Char(string="Secteur")
    contact = fields.Char(string="Contact")
    description = fields.Text(string="Description produit(s)")
    qty = fields.Float(string="Qté", default=1.0)

    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string="Devise")
    amount = fields.Monetary(string="Montant HT (€)", currency_field='currency_id', tracking=True)

    state = fields.Selection([
        ('en_cours', 'En cours'),
        ('envoye', 'Envoyé'),
        ('relance', 'Relancé'),
        ('accepte', 'Accepté'),
        ('refuse', 'Refusé'),
        ('expire', 'Expiré'),
        ('attente_client', 'En attente client'),
    ], string="Statut Devis", default='en_cours', tracking=True, group_expand='_expand_states')

    date_relance_1 = fields.Date(string="Date Relance 1")
    date_relance_2 = fields.Date(string="Date Relance 2")
    date_relance_3 = fields.Date(string="Date Relance 3")

    reponse_client = fields.Char(string="Réponse Client")
    motif_refus = fields.Char(string="Motif Refus / Blocage")

    proba_conversion = fields.Selection([
        ('10', '10%'), ('20', '20%'), ('30', '30%'), ('50', '50%'),
        ('70', '70%'), ('90', '90%'), ('100', '100%'),
    ], string="Proba. Conversion %")

    next_action = fields.Char(string="Action Suivante")
    notes = fields.Text(string="Notes")

    order_ids = fields.One2many('b2fa.order', 'quote_id', string="Commandes liées")
    order_count = fields.Integer(compute='_compute_order_count', string="Nb Commandes")

    active = fields.Boolean(default=True)

    source_ref = fields.Char(
        string="Réf. import Excel", copy=False,
        help="Référence d'origine (colonne 'N° Devis' ou 'N° Commande lié' du fichier Excel importé), "
             "utilisée pour éviter les doublons lors d'un ré-import.")

    sale_order_id = fields.Many2one(
        'sale.order', string="Devis Ventes lié", copy=False, tracking=True,
        help="Devis / commande du module Ventes (sale.order) dont ce devis est issu, "
             "quand il a été créé par la synchronisation automatique.")

    @api.model
    def _expand_states(self, states, domain, order=None):
        return [key for key, val in self._fields['state'].selection]

    @api.depends('order_ids')
    def _compute_order_count(self):
        for rec in self:
            rec.order_count = len(rec.order_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                activity = vals.get('activity_type', 'b2b')
                seq_code = {'b2b': 'b2fa.quote.b2b', 'fund': 'b2fa.quote.fund', 'asie': 'b2fa.quote.asie'}.get(activity)
                vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or 'Nouveau'
        return super().create(vals_list)

    def action_transfer_to_order(self):
        self.ensure_one()
        order = self.env['b2fa.order'].create({
            'quote_id': self.id,
            'activity_type': self.activity_type,
            'client': self.client,
            'contact': self.contact,
            'description': self.description,
            'qty': self.qty,
            'amount_ht': self.amount,
            'company_id': self.company_id.id,
        })
        self.state = 'accepte'
        return {
            'type': 'ir.actions.act_window',
            'name': "Commande",
            'res_model': 'b2fa.order',
            'view_mode': 'form',
            'res_id': order.id,
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Commandes liées",
            'res_model': 'b2fa.order',
            'view_mode': 'list,form',
            'domain': [('quote_id', '=', self.id)],
            'context': {'default_quote_id': self.id, 'default_activity_type': self.activity_type},
        }
