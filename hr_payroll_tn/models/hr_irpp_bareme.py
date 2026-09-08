# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrIrppBareme(models.Model):
    """Barème progressif de l'IRPP tunisien.

    Chaque enregistrement représente une tranche annuelle du barème.
    Le barème est daté (date_from/date_to) afin de pouvoir tenir compte
    des changements introduits par les lois de finances successives.
    """
    _name = 'hr.irpp.bareme'
    _description = "Tranche du barème IRPP"
    _order = 'date_from desc, sequence asc'

    name = fields.Char(compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    date_from = fields.Date(string="Applicable à partir du", required=True)
    date_to = fields.Date(string="Applicable jusqu'au")
    tranche_min = fields.Float(string="Revenu annuel min. (TND)", required=True)
    tranche_max = fields.Float(
        string="Revenu annuel max. (TND)",
        help="Laisser vide pour la dernière tranche (sans plafond).")
    taux = fields.Float(string="Taux (%)", required=True)
    company_id = fields.Many2one(
        'res.company', default=lambda s: s.env.company, required=True)

    @api.depends('tranche_min', 'tranche_max', 'taux')
    def _compute_name(self):
        for rec in self:
            if rec.tranche_max:
                rec.name = "De %.3f à %.3f TND : %.2f%%" % (
                    rec.tranche_min, rec.tranche_max, rec.taux)
            else:
                rec.name = "Au-delà de %.3f TND : %.2f%%" % (
                    rec.tranche_min, rec.taux)

    @api.model
    def compute_irpp(self, revenu_imposable_annuel, company=None, date=None):
        """Calcule l'IRPP annuel dû par application du barème progressif
        par tranches (méthode par différence, tranche par tranche).
        """
        company = company or self.env.company
        date = date or fields.Date.context_today(self)
        domain = [
            ('company_id', '=', company.id),
            ('date_from', '<=', date),
            '|', ('date_to', '=', False), ('date_to', '>=', date),
        ]
        tranches = self.search(domain, order='tranche_min asc')
        if not tranches:
            return 0.0

        revenu = max(revenu_imposable_annuel, 0.0)
        impot = 0.0
        for tranche in tranches:
            borne_inf = tranche.tranche_min
            borne_sup = tranche.tranche_max or float('inf')
            if revenu <= borne_inf:
                continue
            base_tranche = min(revenu, borne_sup) - borne_inf
            if base_tranche > 0:
                impot += base_tranche * (tranche.taux / 100.0)
        return round(impot, 3)
