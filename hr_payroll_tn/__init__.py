from . import models
from . import wizard


def _post_init_hook(env):
    """Rattache le menu 'Paie Tunisie' à l'intérieur de l'app Payroll
    native d'Odoo, en le recherchant dynamiquement (le xmlid exact du
    menu racine Payroll n'est pas stable selon les versions/builds
    Enterprise, donc on évite de le coder en dur)."""
    Menu = env['ir.ui.menu']
    own = env.ref('hr_payroll_tn.menu_paie_tunisie_root', raise_if_not_found=False)
    if not own:
        return

    # 1) Essai le plus fiable : le menu racine dont l'action pointe vers
    #    le modèle hr.payslip (c'est la définition même de l'app Payroll).
    target = Menu.search([
        ('parent_id', '=', False),
        ('action', 'like', 'hr.payslip'),
    ], limit=1)

    # 2) Repli : recherche par nom exact (FR/EN), en excluant notre propre menu.
    if not target:
        target = Menu.search([
            ('parent_id', '=', False),
            ('id', '!=', own.id),
            '|', ('name', '=', 'Payroll'), ('name', '=', 'Paie'),
        ], limit=1)

    # 3) Dernier repli, plus large : nom contenant "payroll" ou "paie".
    if not target:
        target = Menu.search([
            ('parent_id', '=', False),
            ('id', '!=', own.id),
            '|', ('name', 'ilike', 'payroll'), ('name', 'ilike', 'paie'),
        ], limit=1)

    if target:
        own.write({'parent_id': target.id, 'sequence': 100})
    # Si rien n'est trouvé, "Paie Tunisie" reste une app autonome dans le
    # switcher d'apps - fonctionnel dans tous les cas, juste pas imbriqué.

    # ------------------------------------------------------------------
    # Retire les autres rapports PDF liés à hr.payslip (notamment le
    # rapport standard fourni par le module hr_payroll natif) du menu
    # "Imprimer", pour que ce bouton utilise sans ambiguïté notre
    # "Bulletin de paie (Tunisie)" - qui contient Catégorie
    # professionnelle / Échelon. On ne supprime ni n'archive rien (le
    # champ 'active' n'existe pas sur ir.actions.report) : on retire
    # simplement leur binding_model_id, ce qui les fait disparaître du
    # menu "Imprimer" de hr.payslip sans toucher au reste. Réversible à
    # tout moment : Réglages > Technique > Rapports, en réaffectant
    # 'Modèle associé' = 'Fiche de paie' sur l'enregistrement concerné.
    # ------------------------------------------------------------------
    Report = env['ir.actions.report']
    our_reports = env['ir.actions.report']
    for xml_id in ('hr_payroll_tn.action_report_bulletin_paie_tn',
                   'hr_payroll_tn.action_report_bulletin_paie_tn_v2'):
        rep = env.ref(xml_id, raise_if_not_found=False)
        if rep:
            our_reports |= rep
    if our_reports:
        try:
            other_reports = Report.search([
                ('model', '=', 'hr.payslip'),
                ('report_type', '=', 'qweb-pdf'),
                ('id', 'not in', our_reports.ids),
            ])
            if other_reports:
                other_reports.write({'binding_model_id': False})
        except Exception:
            # Ne doit jamais faire échouer l'installation/mise à niveau du
            # module : c'est une simple amélioration de confort (menu
            # "Imprimer"), pas une fonctionnalité critique.
            pass
