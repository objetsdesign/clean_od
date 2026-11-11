# -*- coding: utf-8 -*-
import json
import logging
import requests
from datetime import timedelta
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
class AtelierOrder(models.Model):

    _name = 'atelier.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Ordre de fabrication artisanale "

    name  = fields.Char(string='Référence', required=True,readonly=True,copy=False,default="Nouveau")
    parent_id = fields.Many2one('res.partner',string="client",required=True,tracking=True)
    sales_order_id = fields.Many2one('sale.order',string="Commande client")
    artisan_id=fields.Many2one(comodel_name='res.users',
        string="Artisan responsable",
        default=lambda self: self.env.user,
        tracking=True,)
    date_debut=fields.Date(string="Date de debut")
    date_livraison_prevue=fields.Date(string="Date de livraison prévue")
    state=fields.Selection([('draft','Brouillon'),
                            ('in_progress', 'En cours'),
                            ('done','Terminé'),
                            ('cancel','Annulé')], default='draft',string="State")
    priorite = fields.Selection(
        selection=[
            ('0', 'Normale'),
            ('1', 'Basse'),
            ('2', 'Haute'),
            ('3', 'Très haute'),
        ],
        string="Priorité",
        default='0',
        tracking=True,
    )
    cout_total = fields.Monetary(
        string="Coût total",
        compute='_compute_cout_total',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )
    est_en_retard = fields.Boolean(
        string="En retard",
        compute='_compute_est_en_retard',
        search='_search_est_en_retard',
    )

    @api.depends('date_livraison_prevue', 'state')
    def _compute_est_en_retard(self):
        now = fields.Datetime.now()
        for ordre in self:
            ordre.est_en_retard = bool(
                ordre.date_livraison_prevue
                and ordre.date_livraison_prevue < now
                and ordre.state in ('draft', 'in_progress')
            )

    def _search_est_en_retard(self, operator, value):
        now = fields.Datetime.now()
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [
                ('date_livraison_prevue', '<', now),
                ('state', 'in', ('draft', 'in_progress')),
            ]
        return [
            '|',
            ('date_livraison_prevue', '>=', now),
            ('state', 'not in', ('draft', 'in_progress')),
        ]

    @api.depends('ligne_ids.sous_total')
    def _compute_cout_total(self):
        for ordre in self:
            ordre.cout_total = sum(ordre.ligne_ids.mapped('sous_total'))

    ligne_ids=fields.One2many('atelier.order.line','order_id',string="Matiers premiers")
    company_id=fields.Many2one('res.company',string="Company", default=lambda self: self.env.user.company_id)
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name','Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('atelier.order') or ('Nouveau'
                                                                                         )
        return super().create(vals_list)

    #•	Contrainte : date_livraison_prevue doit être postérieure ou égale à date_debut
    @api.constrains('date_debut', 'date_livraison_prevue')
    def _check_dates(self):
        for ordre in self:
            if (
                    ordre.date_debut
                    and ordre.date_livraison_prevue
                    and ordre.date_livraison_prevue < ordre.date_debut
            ):
                raise ValidationError(
                    _("La date de livraison prévue doit être postérieure ou égale à la date de début.")
                )
    # •	Boutons de workflow : Démarrer, Terminer, Annuler, Remettre en brouillon, avec contrôles (on ne peut pas terminer un ordre sans ligne)

    def action_demarrer(self):
        for ordre in self:
            if ordre.state != 'draft':
                raise UserError(_("Seul un ordre en brouillon peut être démarré."))
            ordre.state = 'in_progress'

    def action_terminer(self):
        for ordre in self:
            if ordre.state != 'in_progress':
                raise UserError(_("Seul un ordre en cours peut être terminé."))
            if not ordre.ligne_ids:
                raise UserError(_("Impossible de terminer un ordre d'atelier sans ligne de matière première."))
            ordre.state = 'done'

    def action_annuler(self):
        for ordre in self:
            if ordre.state == 'done':
                raise UserError(_("Un ordre déjà terminé ne peut pas être annulé."))
            ordre.state = 'cancel'

    def action_remettre_brouillon(self):
        for ordre in self:
            if ordre.state != 'cancel':
                raise UserError(_("Seul un ordre annulé peut être remis en brouillon."))
            # On utilise super().write pour contourner le blocage de modification sur l'état annulé
            super(AtelierOrder, ordre).write({'state': 'draft'})


    def write(self, vals):
        for ordre in self:
            if ordre.state in ('done', 'cancel'):
                raise UserError(
                    _("Un ordre d'atelier terminé ou annulé ne peut plus être modifié.")
                )
        return super().write(vals)
    #•	Un ordre terminé ou annulé ne peut plus être modifié ni supprimé (surcharger write / unlink ou utiliser ondelete)
    @api.ondelete(at_uninstall=False)
    def _unlink_except_termine_annule(self):
        for ordre in self:
            if ordre.state in ('done', 'cancel'):
                raise UserError(
                    _("Un ordre d'atelier terminé ou annulé ne peut pas être supprimé.")
                )

    @api.model
    def _cron_alerte_ordres_en_retard(self):
        """Crée une activité pour l'artisan sur chaque ordre en cours en retard."""
        now = fields.Datetime.now()
        ordres_en_retard = self.search([
            ('state', '=', 'in_prodress'),
            ('date_livraison_prevue', '!=', False),
            ('date_livraison_prevue', '<', now),
            ('artisan_id', '!=', False),
        ])

        activity_type_id = self.env.ref('mail.mail_activity_data_todo').id
        today = fields.Date.context_today(self)

        for ordre in ordres_en_retard:
            # Évite de créer un doublon si une activité de relance est déjà ouverte aujourd'hui
            activite_existante = ordre.activity_ids.filtered(
                lambda a: a.activity_type_id.id == activity_type_id
                and a.user_id == ordre.artisan_id
                and a.summary == _("Ordre d'atelier en retard")
            )
            if not activite_existante:
                ordre.activity_schedule(
                    activity_type_id=activity_type_id,
                    date_deadline=today,
                    summary=_("Ordre d'atelier en retard"),
                    note=_(
                        "L'ordre d'atelier %s a dépassé sa date de livraison prévue (%s).",
                        ordre.name,
                        ordre.date_livraison_prevue,
                    ),
                    user_id=ordre.artisan_id.id,
                )

class AtelierOrdreLigne(models.Model):
    _name = 'atelier.ordre.ligne'
    _description = "Ligne d'ordre d'atelier"

    #  Contrainte SQL sur la quantité strictement positive
    _sql_constraints = [
        (
            'check_quantite_positive',
            'CHECK(quantite > 0)',
            "La quantité d'une ligne doit être strictement positive.",
        ),
    ]
    ordre_id = fields.Many2one(
        comodel_name='atelier.ordre',
        string="Ordre d'atelier",
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='ordre_id.company_id',
        store=True,
    )
    currency_id = fields.Many2one(
        related='ordre_id.currency_id',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string="Matière première",
        required=True,
    )
    quantite = fields.Float(
        string="Quantité",
        default=1.0,
        required=True,
    )
    prix_unitaire = fields.Float(
        string="Prix unitaire",
        compute='_compute_prix_unitaire',
        store=True,
        readonly=False,
    )
    sous_total = fields.Monetary(
        string="Sous-total",
        compute='_compute_sous_total',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('product_id')
    def _compute_prix_unitaire(self):
        for ligne in self:
            if ligne.product_id:
                ligne.prix_unitaire = ligne.product_id.standard_price
            else:
                ligne.prix_unitaire = 0.0

    @api.depends('quantite', 'prix_unitaire')
    def _compute_sous_total(self):
        for ligne in self:
            ligne.sous_total = ligne.quantite * ligne.prix_unitaire

