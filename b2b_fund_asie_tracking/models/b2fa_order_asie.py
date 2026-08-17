# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2faOrderAsie(models.Model):
    """Commande Asie — modèle 100% indépendant de b2fa.order (B2B Classique /
    Fund Raising) : pas de champ 'activity_type' partagé, pas de ligne dans la
    même table, aucune relation Odoo vers b2fa.order/b2fa.quote. Seul lien
    conservé : vers b2fa.quote.asie (son propre devis) et, en lecture, vers
    sale.order (via la synchronisation depuis sale.order.sky)."""
    _name = 'b2fa.order.asie'
    _description = "Commande Asie (modèle indépendant)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_commande desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string="N° Commande", required=True, copy=False, tracking=True,
        default=lambda self: "Nouveau",
        help="Format conseillé : CMD-ASIE-AAAA-NNN (ex: CMD-ASIE-2026-001)")

    quote_id = fields.Many2one('b2fa.quote.asie', string="N° Devis lié", tracking=True)

    date_commande = fields.Date(string="Date Commande", default=fields.Date.context_today, tracking=True)
    client = fields.Char(string="Client", required=True, tracking=True)
    contact = fields.Char(string="Contact")
    description = fields.Text(string="Description produit(s)")
    qty = fields.Float(string="Qté", default=1.0)

    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string="Devise")

    amount_ht = fields.Monetary(string="Montant HT (€)", currency_field='currency_id', tracking=True)
    cost = fields.Monetary(string="Coût (€)", currency_field='currency_id',
                            help="Coût de revient")
    deposit_received = fields.Monetary(string="Acompte reçu", currency_field='currency_id')
    balance_due = fields.Monetary(string="Solde à recevoir", currency_field='currency_id',
                                   compute='_compute_balance_due', store=True)
    margin = fields.Monetary(string="Marge (€)", currency_field='currency_id',
                              compute='_compute_margin', store=True)

    state = fields.Selection([
        ('confirmee', 'Confirmée'),
        ('en_production', 'En production'),
        ('controle_qualite', 'Contrôle qualité'),
        ('prete_expedier', 'Prête à expédier'),
        ('expediee', 'Expédiée'),
        ('livree', 'Livrée'),
        ('litige', 'Litige'),
        ('annulee', 'Annulée'),
    ], string="Statut Commande", default='confirmee', tracking=True, group_expand='_expand_states')

    production_source = fields.Selection([
        ('tunisie_vri', 'Tunisie VRI'),
        ('tunisie_bsi', 'Tunisie BSI'),
        ('chine', 'Chine'),
        ('stock_europe', 'Stock Europe'),
        ('multi_source', 'Multi-source'),
        ('vietnam', 'Vietnam'),
        ('inde', 'Inde'),
        ('bangladesh', 'Bangladesh'),
        ('multi_source_asie', 'Multi-source Asie'),
    ], string="Source Production")

    date_prod_prevue = fields.Date(string="Date prod. prévue")
    date_prod_reelle = fields.Date(string="Date prod. réelle")
    date_expedition = fields.Date(string="Date expédition")
    carrier = fields.Char(string="Transporteur")
    logistics_fees = fields.Monetary(string="Frais logistiques", currency_field='currency_id')
    tracking_number = fields.Char(string="N° tracking")
    date_livraison_prevue = fields.Date(string="Date livraison prévue")
    date_livraison_reelle = fields.Date(string="Date livraison réelle")
    notes_incidents = fields.Text(string="Notes / Incidents")

    delay_delivery = fields.Boolean(string="Livraison en retard", compute='_compute_delay_delivery', store=True)

    active = fields.Boolean(default=True)

    source_ref = fields.Char(
        string="Réf. import Excel", copy=False,
        help="Référence d'origine (colonne 'N° Commande' du fichier Excel importé), "
             "utilisée pour éviter les doublons lors d'un ré-import.")
    quote_ref_text = fields.Char(
        string="N° Devis lié (texte brut)",
        help="Référence de devis telle que saisie dans le fichier Excel d'origine (colonne "
             "'N° Devis lié'). Conservée telle quelle quand elle ne correspond à aucun devis "
             "existant dans le système.")

    # Lien VERS sale.order uniquement (aucun champ ajouté sur sale.order).
    sale_order_id = fields.Many2one(
        'sale.order', string="Commande Ventes liée", copy=False, tracking=True,
        help="Commande du module Ventes (sale.order) dont cette commande Asie est issue, "
             "quand elle a été créée par la synchronisation automatique depuis sale.order.sky.")

    @api.model
    def _expand_states(self, states, domain, order=None):
        return [key for key, val in self._fields['state'].selection]

    @api.depends('amount_ht', 'deposit_received')
    def _compute_balance_due(self):
        for rec in self:
            rec.balance_due = (rec.amount_ht or 0.0) - (rec.deposit_received or 0.0)

    @api.depends('amount_ht', 'cost')
    def _compute_margin(self):
        for rec in self:
            rec.margin = (rec.amount_ht or 0.0) - (rec.cost or 0.0)

    @api.depends('date_livraison_prevue', 'date_livraison_reelle', 'state')
    def _compute_delay_delivery(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_livraison_reelle and rec.date_livraison_prevue:
                rec.delay_delivery = rec.date_livraison_reelle > rec.date_livraison_prevue
            elif not rec.date_livraison_reelle and rec.date_livraison_prevue and rec.state not in ('livree', 'annulee'):
                rec.delay_delivery = today > rec.date_livraison_prevue
            else:
                rec.delay_delivery = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('b2fa.order.asie') or 'Nouveau'
        return super().create(vals_list)

    @api.model
    def _cron_update_delay_delivery(self):
        """Recompute the delay flag daily for open orders (stored field depends on today's date)."""
        orders = self.search([('state', 'not in', ('livree', 'annulee'))])
        orders._compute_delay_delivery()

    @api.onchange('quote_id')
    def _onchange_quote_id(self):
        if self.quote_id:
            self.client = self.quote_id.client
            self.contact = self.quote_id.contact
            self.description = self.quote_id.description
            self.qty = self.quote_id.qty
            self.amount_ht = self.quote_id.amount
