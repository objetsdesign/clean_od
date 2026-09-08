# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- CNSS ---
    cnss_employer_number = fields.Char(string="Matricule CNSS employeur")
    cnss_employee_rate = fields.Float(
        string="Taux CNSS salarié (%)", default=9.18,
        help="Part salariale retenue sur le salaire brut soumis à CNSS.")
    cnss_employer_rate = fields.Float(
        string="Taux CNSS patronal (%)", default=16.57,
        help="Part patronale calculée sur le salaire brut soumis à CNSS.")
    cnss_accident_travail_rate = fields.Float(
        string="Taux Accident du Travail (%)", default=0.4,
        help="Taux variable selon le secteur d'activité (0,4% à 4%).")

    # --- IRPP ---
    irpp_deduction_chef_famille = fields.Float(
        string="Déduction chef de famille (TND/an)", default=300.0)
    irpp_deduction_par_enfant = fields.Float(
        string="Déduction par enfant à charge (TND/an)", default=100.0)
    irpp_nb_enfants_max = fields.Integer(
        string="Nombre max. d'enfants déductibles", default=4)
    irpp_css_rate = fields.Float(
        string="Contribution Sociale de Solidarité - CSS (%)", default=1.0,
        help="Contribution additionnelle éventuelle selon la Loi de Finances "
             "en vigueur. Mettre à 0 si non applicable.")
