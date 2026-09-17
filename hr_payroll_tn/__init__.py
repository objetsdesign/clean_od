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
    # Désactive les autres rapports PDF liés à hr.payslip (notamment le
    # rapport standard fourni par le module hr_payroll natif) pour que le
    # bouton "Imprimer" utilise sans ambiguïté notre "Bulletin de paie
    # (Tunisie)" - qui contient Catégorie professionnelle / Échelon.
    # Réversible à tout moment : Réglages > Technique > Rapports, en
    # réactivant l'enregistrement archivé.
    # ------------------------------------------------------------------
    Report = env['ir.actions.report']
    our_report = env.ref(
        'hr_payroll_tn.action_report_bulletin_paie_tn', raise_if_not_found=False)
    if our_report:
        other_reports = Report.search([
            ('model', '=', 'hr.payslip'),
            ('report_type', '=', 'qweb-pdf'),
            ('id', '!=', our_report.id),
        ])
        if other_reports:
            other_reports.write({'active': False})
