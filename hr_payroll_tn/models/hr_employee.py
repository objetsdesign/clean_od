# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    cin = fields.Char(string="N° CIN")
    cin_delivrance_date = fields.Date(string="Date délivrance CIN")
    cin_delivrance_lieu = fields.Char(string="Lieu délivrance CIN")

    cnss_number = fields.Char(string="N° CNSS (matricule assuré)")
    date_affiliation_cnss = fields.Date(string="Date d'affiliation CNSS")

    situation_familiale = fields.Selection([
        ('celibataire', 'Célibataire'),
        ('marie', 'Marié(e)'),
        ('divorce', 'Divorcé(e)'),
        ('veuf', 'Veuf(ve)'),
    ], string="Situation familiale", default='celibataire')

    chef_de_famille = fields.Boolean(string="Chef de famille")
    nombre_enfants_charge = fields.Integer(string="Nombre d'enfants à charge")
    nombre_parents_charge = fields.Integer(
        string="Nombre de parents à charge", default=0)

    rib = fields.Char(string="RIB")
    banque_id = fields.Many2one('res.bank', string="Banque")

    loan_ids = fields.One2many('hr.loan', 'employee_id', string="Prêts / Avances")
    loan_count = fields.Integer(compute='_compute_loan_count', string="Nb. prêts")

    def _compute_loan_count(self):
        for emp in self:
            emp.loan_count = len(emp.loan_ids)

    def action_view_loans(self):
        self.ensure_one()
        return {
            'name': "Prêts / Avances",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.loan',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
