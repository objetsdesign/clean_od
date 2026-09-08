# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    departement_id = fields.Many2one(
        related='employee_id.department_id', store=True, string="Département")

    # ------------------------------------------------------------------
    # Helpers appelés depuis les règles de salaire (code Python)
    # ------------------------------------------------------------------
    def _tn_get_company(self):
        return self.contract_id.company_id or self.company_id or self.env.company

    def _tn_cnss_salariale(self, base_cnss):
        """Retenue CNSS part salariale sur la base cotisable."""
        company = self._tn_get_company()
        return -round(base_cnss * (company.cnss_employee_rate / 100.0), 3)

    def _tn_cnss_patronale(self, base_cnss):
        """Charge CNSS part patronale (n'impacte pas le net à payer, mais
        est utile pour le coût employeur et la télédéclaration)."""
        company = self._tn_get_company()
        return round(base_cnss * (company.cnss_employer_rate / 100.0), 3)

    def _tn_accident_travail(self, base_cnss):
        company = self._tn_get_company()
        return round(base_cnss * (company.cnss_accident_travail_rate / 100.0), 3)

    def _tn_deduction_situation_familiale_annuelle(self):
        """Déductions annuelles pour situation familiale, selon barème
        configuré sur la société (chef de famille + enfants à charge)."""
        self.ensure_one()
        company = self._tn_get_company()
        employee = self.employee_id
        deduction = 0.0
        if employee.chef_de_famille:
            deduction += company.irpp_deduction_chef_famille
            nb_enfants = min(employee.nombre_enfants_charge,
                              company.irpp_nb_enfants_max)
            deduction += nb_enfants * company.irpp_deduction_par_enfant
        return deduction

    def _tn_irpp_mensuel(self, brut_imposable_mensuel, base_cnss_mensuelle):
        """Calcule la retenue IRPP mensuelle :
        1) Annualise le salaire brut imposable et la base CNSS
        2) Déduit la CNSS annuelle et les déductions familiales
        3) Applique le barème progressif (hr.irpp.bareme)
        4) Ramène l'impôt annuel au mois et ajoute la CSS le cas échéant
        """
        self.ensure_one()
        company = self._tn_get_company()
        Bareme = self.env['hr.irpp.bareme']

        brut_annuel = brut_imposable_mensuel * 12.0
        cnss_annuelle = base_cnss_mensuelle * 12.0 * (
            company.cnss_employee_rate / 100.0)
        deduction_familiale = self._tn_deduction_situation_familiale_annuelle()

        revenu_imposable = max(
            brut_annuel - cnss_annuelle - deduction_familiale, 0.0)

        irpp_annuel = Bareme.compute_irpp(
            revenu_imposable, company=company,
            date=self.date_to or fields.Date.context_today(self))

        css_annuelle = revenu_imposable * (company.irpp_css_rate / 100.0)

        irpp_mensuel = (irpp_annuel + css_annuelle) / 12.0
        return -round(irpp_mensuel, 3)

    def _tn_retenue_prets(self):
        """Somme des échéances de prêts non encore retenues pour l'employé,
        à imputer sur ce bulletin. Marque les échéances comme retenues."""
        self.ensure_one()
        total = 0.0
        loans = self.env['hr.loan'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'running'),
        ])
        for loan in loans:
            line = loan.line_ids.filtered(lambda l: not l.paid)[:1]
            if line:
                total += line.montant
                if not self.env.context.get('tn_dry_run'):
                    line.write({'paid': True, 'payslip_id': self.id})
        return -round(total, 3)

    def _tn_jours_travailles(self):
        """Nombre de jours/heures effectivement travaillés sur la période,
        basé sur les worked_days_line_ids (feuille de présence / pointage)."""
        self.ensure_one()
        wds = self.worked_days_line_ids.filtered(
            lambda l: l.code == 'WORK100')
        return sum(wds.mapped('number_of_days')), sum(wds.mapped('number_of_hours'))
