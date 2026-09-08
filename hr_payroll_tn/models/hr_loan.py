# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrLoan(models.Model):
    _name = 'hr.loan'
    _description = "Prêt / Avance sur salaire"
    _order = 'date_demande desc'

    name = fields.Char(string="Référence", default="Nouveau",
                        copy=False, readonly=True)
    employee_id = fields.Many2one('hr.employee', string="Employé",
                                   required=True, ondelete='cascade')
    date_demande = fields.Date(string="Date de la demande",
                                default=fields.Date.context_today)
    montant = fields.Monetary(string="Montant du prêt", required=True)
    nombre_echeances = fields.Integer(string="Nombre d'échéances",
                                       default=1, required=True)
    montant_echeance = fields.Monetary(
        string="Montant par échéance", compute='_compute_montant_echeance',
        store=True)
    montant_rembourse = fields.Monetary(
        string="Montant remboursé", compute='_compute_montant_rembourse',
        store=True)
    solde_restant = fields.Monetary(
        string="Solde restant", compute='_compute_montant_rembourse',
        store=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda s: s.env.company.currency_id)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('validate', 'Validé'),
        ('running', 'En cours'),
        ('done', 'Soldé'),
        ('cancel', 'Annulé'),
    ], default='draft', string="Statut", tracking=True)
    line_ids = fields.One2many('hr.loan.line', 'loan_id', string="Échéancier")
    note = fields.Text(string="Motif / Note")
    company_id = fields.Many2one(
        'res.company', default=lambda s: s.env.company)

    @api.depends('montant', 'nombre_echeances')
    def _compute_montant_echeance(self):
        for loan in self:
            loan.montant_echeance = (
                loan.montant / loan.nombre_echeances
                if loan.nombre_echeances else 0.0)

    @api.depends('line_ids.montant', 'line_ids.paid', 'montant')
    def _compute_montant_rembourse(self):
        for loan in self:
            rembourse = sum(loan.line_ids.filtered('paid').mapped('montant'))
            loan.montant_rembourse = rembourse
            loan.solde_restant = loan.montant - rembourse

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.loan') or 'Nouveau'
        return super().create(vals_list)

    def action_validate(self):
        for loan in self:
            if loan.montant <= 0 or loan.nombre_echeances <= 0:
                raise ValidationError(
                    "Le montant et le nombre d'échéances doivent être positifs.")
            loan.line_ids.unlink()
            lines = []
            for i in range(1, loan.nombre_echeances + 1):
                lines.append((0, 0, {
                    'sequence': i,
                    'montant': loan.montant_echeance,
                }))
            loan.write({'state': 'running', 'line_ids': lines})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def get_echeance_du_mois(self, date_from, date_to):
        """Retourne le montant de l'échéance non payée à retenir sur la
        période de paie donnée (utilisé par la règle de salaire PRET)."""
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: not l.paid)[:1]
        return line.montant if line else 0.0


class HrLoanLine(models.Model):
    _name = 'hr.loan.line'
    _description = "Échéance de prêt"
    _order = 'sequence'

    loan_id = fields.Many2one('hr.loan', required=True, ondelete='cascade')
    sequence = fields.Integer(string="N° échéance")
    montant = fields.Monetary(string="Montant")
    currency_id = fields.Many2one(
        related='loan_id.currency_id', store=True)
    paid = fields.Boolean(string="Retenue effectuée", default=False)
    payslip_id = fields.Many2one('hr.payslip', string="Bulletin de paie")
