# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2faQuoteAsie(models.Model):
    """Devis Asie — modèle 100% indépendant de b2fa.quote (B2B Classique /
    Fund Raising) : pas de champ 'activity_type' partagé, pas de ligne dans la
    même table, aucune relation Odoo (Many2one/One2many) vers b2fa.quote ou
    b2fa.order. Seul point commun : la structure des champs, dupliquée pour
    rester lisible et pour ne dépendre de rien côté B2B/Fund."""
    _name = 'b2fa.quote.asie'
    _description = "Devis Asie (modèle indépendant)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_devis desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string="N° Devis", required=True, copy=False, tracking=True,
        default=lambda self: "Nouveau",
        help="Format conseillé : DEV-ASIE-AAAA-NNN (ex: DEV-ASIE-2026-001)")

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

    order_ids = fields.One2many('b2fa.order.asie', 'quote_id', string="Commandes liées")
    order_count = fields.Integer(compute='_compute_order_count', string="Nb Commandes")

    active = fields.Boolean(default=True)

    source_ref = fields.Char(
        string="Réf. import Excel", copy=False,
        help="Référence d'origine (colonne 'N° Devis' ou 'N° Commande lié' du fichier "
             "Excel importé), utilisée pour éviter les doublons lors d'un ré-import.")

    # Lien VERS sale.order uniquement (aucun champ ajouté sur sale.order).
    # Normalement renseigné via la fiche sale.order.sky lors de la
    # synchronisation, jamais via une classification portée par sale.order.
    sale_order_id = fields.Many2one(
        'sale.order', string="Devis Ventes lié", copy=False, tracking=True,
        help="Devis / commande du module Ventes (sale.order) dont ce devis Asie est issu, "
             "quand il a été créé par la synchronisation automatique depuis sale.order.sky.")

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
                vals['name'] = self.env['ir.sequence'].next_by_code('b2fa.quote.asie') or 'Nouveau'
        return super().create(vals_list)

    def action_transfer_to_order(self):
        self.ensure_one()
        order = self.env['b2fa.order.asie'].create({
            'quote_id': self.id,
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
            'res_model': 'b2fa.order.asie',
            'view_mode': 'form',
            'res_id': order.id,
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Commandes liées",
            'res_model': 'b2fa.order.asie',
            'view_mode': 'list,form',
            'domain': [('quote_id', '=', self.id)],
            'context': {'default_quote_id': self.id},
        }
