# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    departement_id = fields.Many2one(
        related='employee_id.department_id', store=True, string="Département")
    categorie_pro = fields.Selection(
        related='contract_id.categorie_pro', string="Catégorie professionnelle")
    echelon = fields.Selection(
        related='contract_id.echelon', string="Échelon")

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

    def _tn_irpp_detail(self, brut_imposable_mensuel, base_cnss_mensuelle):
        """Rassemble les paramètres propres au bulletin/contrat (taux
        société, déductions familiales de l'employé) et délègue le calcul
        complet au module IRPP autonome
        `hr.irpp.bareme.calculer_irpp_mensuel()` (models/hr_irpp_bareme.py).
        Renvoie le détail complet (IRPP et CSS distincts + cumul)."""
        self.ensure_one()
        company = self._tn_get_company()
        employee = self.employee_id
        nb_parents = min(employee.nombre_parents_charge or 0,
                          company.irpp_nb_parents_max)
        return self.env['hr.irpp.bareme'].calculer_irpp_mensuel(
            salaire_brut_imposable_mensuel=brut_imposable_mensuel,
            base_cnss_mensuelle=base_cnss_mensuelle,
            taux_cnss_salarie=company.cnss_employee_rate,
            taux_abattement_frais_pro=company.irpp_abattement_frais_pro_rate,
            plafond_abattement_frais_pro=company.irpp_abattement_frais_pro_max,
            deduction_familiale_annuelle=self._tn_deduction_situation_familiale_annuelle(),
            nb_parents_charge=nb_parents,
            taux_deduction_parent=company.irpp_deduction_parent_rate,
            plafond_deduction_parent_annuel=company.irpp_deduction_parent_max,
            taux_css=company.irpp_css_rate,
            company=company,
            date=self.date_to or fields.Date.context_today(self),
        )

    def _tn_irpp_mensuel(self, brut_imposable_mensuel, base_cnss_mensuelle):
        """Retenue IRPP mensuelle seule (ligne IRPP du bulletin)."""
        detail = self._tn_irpp_detail(brut_imposable_mensuel, base_cnss_mensuelle)
        return -detail['irpp_mensuel']

    def _tn_css_mensuelle(self, brut_imposable_mensuel, base_cnss_mensuelle):
        """Retenue CSS mensuelle seule (ligne CSS distincte du bulletin)."""
        detail = self._tn_irpp_detail(brut_imposable_mensuel, base_cnss_mensuelle)
        return -detail['css_mensuelle']

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

    def _tn_jours_non_payes(self):
        """Nombre de jours d'absence NON payée sur la période (congé sans
        solde, absence injustifiée, etc.), à déduire du salaire de base.
        S'appuie sur les lignes de jours travaillés générées automatiquement
        par hr_holidays / hr_payroll_holidays pour chaque congé validé."""
        self.ensure_one()
        lignes_non_payees = self.worked_days_line_ids.filtered(
            lambda l: l.work_entry_type_id
            and getattr(l.work_entry_type_id, 'is_leave', False)
            and getattr(l.work_entry_type_id, 'unpaid', False))
        return sum(lignes_non_payees.mapped('number_of_days'))

    def _tn_get_leaves_summary(self):
        """Récapitulatif des congés/absences de la période, pour affichage
        sur le bulletin de paie (regroupés par type de congé)."""
        self.ensure_one()
        groupes = {}
        for line in self.worked_days_line_ids:
            entry_type = line.work_entry_type_id
            if not entry_type or not getattr(entry_type, 'is_leave', False):
                continue
            key = entry_type.name
            if key not in groupes:
                groupes[key] = {
                    'name': key,
                    'days': 0.0,
                    'hours': 0.0,
                    'unpaid': getattr(entry_type, 'unpaid', False),
                }
            groupes[key]['days'] += line.number_of_days
            groupes[key]['hours'] += line.number_of_hours
        return list(groupes.values())
