# -*- coding: utf-8 -*-
{
    'name': 'Paie Tunisie - Payroll Tunisia',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': "Module de paie tunisienne : CNSS, IRPP, bulletin de paie, "
               "prêts, congés, pointage, traitement par lot",
    'description': """
Paie Tunisie
============
Module de paie adapté à la législation tunisienne, développé comme
implémentation originale (structures, règles de salaire, vues et rapports
propres à ce module - aucune ligne de code d'un module tiers n'est reprise).

Fonctionnalités
----------------
* Structure salariale tunisienne (Brut, CNSS, IRPP, Net)
* Calcul automatique de la CNSS (part salariale / part patronale)
* Calcul automatique de l'IRPP selon le barème progressif tunisien,
  avec prise en compte de la situation familiale (chef de famille,
  nombre d'enfants et de parents à charge)
* Bulletin de paie conforme au format tunisien (PDF)
* Traitement et impression des bulletins par lot et par département
* Tableau de bord de télédéclaration CNSS (export + impression)
* Gestion des prêts et avances sur salaire avec échéancier de retenues
* Gestion des congés (maladie, jours fériés, absences) et du pointage
  (manuel ou machine via Attendances)
* Barème IRPP et taux CNSS configurables (mise à jour selon la Loi de
  Finances de chaque année)

NB : les taux CNSS et tranches IRPP fournis par défaut sont indicatifs et
DOIVENT être vérifiés/ajustés par l'utilisateur selon la réglementation en
vigueur (CNSS / Loi de Finances) avant toute utilisation en production.
""",
    'author': 'Votre Société',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'hr_contract',
        'hr_payroll',
        'hr_holidays',
        'hr_attendance',
        'calendar',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_payroll_tn_security.xml',
        'data/hr_loan_sequence_data.xml',
        'data/hr_salary_rule_category_tn_data.xml',
        'data/hr_irpp_bareme_data.xml',
        'data/hr_payroll_structure_tn_data.xml',
        'data/hr_salary_rule_tn_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_loan_views.xml',
        'report/bulletin_paie_report.xml',
        'report/bulletin_paie_template.xml',
        'report/ir_actions_server_bulletin_paie.xml',
        'report/cnss_declaration_template.xml',
        'views/hr_payslip_views.xml',
        'views/hr_irpp_bareme_views.xml',
        'views/res_config_settings_views.xml',
        'views/cnss_dashboard_views.xml',
        'wizard/hr_payslip_batch_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        # CSS dédié et isolé du bulletin de paie (aucune logique de calcul,
        # uniquement la mise en forme), chargé pour l'impression du rapport.
        'web.report_assets_common': [
            'hr_payroll_tn/static/src/css/bulletin_paie.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': '_post_init_hook',
}
