# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cnss_employee_rate = fields.Float(
        related='company_id.cnss_employee_rate', readonly=False)
    cnss_employer_rate = fields.Float(
        related='company_id.cnss_employer_rate', readonly=False)
    cnss_accident_travail_rate = fields.Float(
        related='company_id.cnss_accident_travail_rate', readonly=False)
    cnss_employer_number = fields.Char(
        related='company_id.cnss_employer_number', readonly=False)
    irpp_deduction_chef_famille = fields.Float(
        related='company_id.irpp_deduction_chef_famille', readonly=False)
    irpp_deduction_par_enfant = fields.Float(
        related='company_id.irpp_deduction_par_enfant', readonly=False)
    irpp_nb_enfants_max = fields.Integer(
        related='company_id.irpp_nb_enfants_max', readonly=False)
    irpp_css_rate = fields.Float(
        related='company_id.irpp_css_rate', readonly=False)
