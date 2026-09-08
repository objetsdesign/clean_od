# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslipBatchWizard(models.TransientModel):
    _name = 'hr.payslip.batch.wizard'
    _description = "Traitement des bulletins par lot / département"

    date_from = fields.Date(string="Du", required=True,
                             default=lambda s: fields.Date.today().replace(day=1))
    date_to = fields.Date(string="Au", required=True,
                           default=fields.Date.today)
    department_ids = fields.Many2many(
        'hr.department', string="Départements",
        help="Laisser vide pour traiter tous les départements.")
    employee_ids = fields.Many2many(
        'hr.employee', string="Employés",
        help="Laisser vide pour traiter tous les employés éligibles.")
    structure_id = fields.Many2one(
        'hr.payroll.structure', string="Structure salariale",
        default=lambda s: s.env.ref(
            'hr_payroll_tn.hr_payroll_structure_tn', raise_if_not_found=False))

    def _get_employees(self):
        domain = [('contract_id', '!=', False)]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.employee_ids:
            domain.append(('id', 'in', self.employee_ids.ids))
        return self.env['hr.employee'].search(domain)

    def action_generate_payslips(self):
        self.ensure_one()
        employees = self._get_employees()
        Payslip = self.env['hr.payslip']
        slips = self.env['hr.payslip']
        for employee in employees:
            contract = employee.contract_id
            if not contract:
                continue
            slip = Payslip.create({
                'name': "Bulletin - %s" % employee.name,
                'employee_id': employee.id,
                'contract_id': contract.id,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'struct_id': self.structure_id.id if self.structure_id else False,
            })
            slip.compute_sheet()
            slips |= slip
        return {
            'name': "Bulletins de paie générés",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('id', 'in', slips.ids)],
        }

    def action_print_payslips(self):
        self.ensure_one()
        employees = self._get_employees()
        slips = self.env['hr.payslip'].search([
            ('employee_id', 'in', employees.ids),
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
        ])
        if not slips:
            return False
        return self.env.ref(
            'hr_payroll_tn.action_report_bulletin_paie_tn'
        ).report_action(slips)
