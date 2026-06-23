from collections import defaultdict
from datetime import date, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    shared_line_ids = fields.Many2many(
        'account.analytic.line',
        'account_analytic_line_shared_rel',
        'line_id',
        'shared_id',
        string='Lignes partagées'
    )
    is_shared_copy = fields.Boolean(string="Copie partagée", default=False)

    sequence_date = fields.Char(string='Sequence Date', compute='_compute_sequence_date', store=True)
    manager_id = fields.Many2one(
        'hr.employee', string="N+1 / Responsable",
        related="emplee_id.parent_id", store=True, readonly=True
    )
    user_ids = fields.Many2many(
        'res.users',
        string='Animateurs (Pilotes)',
        domain=lambda self: [
            ('groups_id', 'in', self.env.ref('hr.group_hr_user').id),
            ('employee_ids', '!=', False)
        ]
    )
    user_id = fields.Many2one('res.users')
    date_debut = fields.Datetime('Date Début')
    date_fin = fields.Datetime('Date Fin')
    tranch_horaire = fields.Char('Tranche horaire')
    effort_estime = fields.Char('Effort estimé (h/j)')
    tach_al = fields.Char('Tache simple')
    display_task = fields.Char('Tâche affichée', compute="_compute_display_task")
    desc_od = fields.Text(string='Description OD')

    linked_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_linked_users',
        string="Utilisateurs liés",
    )
    emplee_id = fields.Many2one('hr.employee')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        pass

    @api.depends('user_id', 'employee_id.user_id')
    def _compute_linked_users(self):
        for line in self:
            users = line.user_id | (line.employee_id.user_id if line.employee_id else self.env['res.users'])
            line.linked_user_ids = users

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'name' in vals and not vals.get('tach_al'):
                vals['tach_al'] = vals['name']

        lines = super().create(vals_list)

        for line in lines:
            if line.is_shared_copy:
                continue

            animateur_user = line.user_id
            collab_employee = line.emplee_id

            animateur_employee = self.env['hr.employee'].search(
                [('user_id', '=', animateur_user.id)], limit=1
            ) if animateur_user else False

            collab_user = collab_employee.user_id if collab_employee else False

            twins = []

            if animateur_user and collab_employee and collab_user:
                if animateur_employee and line.employee_id != animateur_employee:
                    line.sudo().write({'employee_id': animateur_employee.id})

                twin_vals = {
                    'name': line.name,
                    'tach_al': line.tach_al,
                    'project_id': line.project_id.id if line.project_id else False,
                    'task_id': line.task_id.id if line.task_id else False,
                    'unit_amount': line.unit_amount,
                    'date': line.date,
                    'date_debut': line.date_debut,
                    'date_fin': line.date_fin,
                    'tranch_horaire': line.tranch_horaire,
                    'effort_estime': line.effort_estime,
                    'priorite': line.priorite,
                    'importance': line.importance,
                    'statut': line.statut,
                    'avancement': line.avancement,
                    'desc_od': line.desc_od,
                    'user_id': collab_user.id,
                    'employee_id': collab_employee.id,
                    'emplee_id': collab_employee.id,
                    'is_shared_copy': True,
                }
                twin = super(AccountAnalyticLine, self.sudo()).create([twin_vals])
                twins.append(twin)

            elif animateur_user and not collab_employee:
                if animateur_employee and line.employee_id != animateur_employee:
                    line.sudo().write({'employee_id': animateur_employee.id})

            elif collab_employee and not animateur_user:
                if line.employee_id != collab_employee:
                    line.sudo().write({'employee_id': collab_employee.id})

            if twins:
                line.sudo().write({'shared_line_ids': [(4, t.id) for t in twins]})
                for twin in twins:
                    twin.sudo().write({'shared_line_ids': [(4, line.id)]})

        for line in lines:
            if line.task_id and (line.date_debut or line.date_fin or line.desc_od):
                task_vals = {}
                if line.date_debut:
                    task_vals['planned_date_begin'] = line.date_debut
                if line.date_fin:
                    task_vals['date_deadline'] = line.date_fin
                if line.desc_od:
                    task_vals['description'] = '<p>' + line.desc_od.replace(chr(10), '</p><p>') + '</p>'
                if task_vals:
                    line.task_id.with_context(syncing_task_dates=True).sudo().write(task_vals)

        return lines

    def write(self, vals):
        result = super().write(vals)

        SYNC_FIELDS = {
            'name', 'tach_al', 'project_id', 'task_id', 'unit_amount', 'date',
            'date_debut', 'date_fin', 'tranch_horaire', 'effort_estime',
            'priorite', 'importance', 'statut', 'avancement', 'desc_od',
        }
        fields_to_sync = SYNC_FIELDS & set(vals.keys())

        if not fields_to_sync or self.env.context.get('syncing_shared'):
            return result

        sync_vals = {k: vals[k] for k in fields_to_sync}

        for line in self:
            if line.is_shared_copy:
                continue
            if line.shared_line_ids:
                line.shared_line_ids.with_context(syncing_shared=True).sudo().write(sync_vals)

        if not self.env.context.get('syncing_task_dates'):
            date_debut = vals.get('date_debut')
            date_fin = vals.get('date_fin')
            desc_od = vals.get('desc_od')
            if date_debut is not None or date_fin is not None or desc_od is not None:
                for line in self:
                    if line.task_id:
                        task_vals = {}
                        if date_debut is not None:
                            task_vals['planned_date_begin'] = date_debut
                        if date_fin is not None:
                            task_vals['date_deadline'] = date_fin
                        if desc_od is not None:
                            task_vals['description'] = '<p>' + desc_od.replace(chr(10), '</p><p>') + '</p>' if desc_od else desc_od
                        if task_vals:
                            line.task_id.with_context(syncing_task_dates=True).sudo().write(task_vals)

        return result

    def unlink(self):
        twins_to_delete = self.env['account.analytic.line']
        for line in self:
            if not line.is_shared_copy:
                twins_to_delete |= line.shared_line_ids
        result = super().unlink()
        if twins_to_delete:
            twins_to_delete.sudo().unlink()
        return result

    @api.depends('project_id', 'task_id', 'tach_al')
    def _compute_display_task(self):
        for line in self:
            if line.project_id and line.task_id:
                line.display_task = f"{line.project_id.name or ''} - {line.task_id.name or ''}"
            else:
                line.display_task = line.tach_al or ''

    def action_open_form(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Timesheet",
            "res_model": "account.analytic.line",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    @api.depends('date', 'employee_id')
    def _compute_sequence_date(self):
        for line in self:
            if line.employee_id:
                lines = self.search([
                    ('employee_id', '=', line.employee_id.id)
                ], order='date,id')
                index = lines.ids.index(line.id) + 1
                line.sequence_date = (line.date or fields.Date.today()).strftime('%Y%m%d') + f'_{index}'
            else:
                line.sequence_date = (line.date or fields.Date.today()).strftime('%Y%m%d') + '_0'

    etape = fields.Selection([
        ('tache_critique', 'Tache critique'),
        ('validation', 'Validation'),
        ('relance', 'Relance'),
        ('urgence', 'Urgence'),
    ], string="Etape", default='validation')
    deadline = fields.Date(string="Deadline")
    priorite = fields.Selection([
        ('haute', 'Haute'),
        ('moyenne', 'Moyenne'),
        ('basse', 'Basse'),
    ], string="Priorité", default='moyenne')
    importance = fields.Selection([
        ('mineur', 'Mineure'),
        ('majeure', 'Majeure'),
        ('strategique', 'Stratégique'),
    ], string="Importance", default='mineur')
    statut = fields.Selection([
        ('bloque', 'Bloqué'),
        ('en_cours', 'En cours'),
        ('afaire', 'À faire'),
    ], string="Statut", default='bloque')
    blocage = fields.Boolean(string="Blocage")
    avancement = fields.Integer(string="% Avancement")

    week_number = fields.Integer(
        string="Week Number",
        compute="_compute_week_number",
        store=True,
    )
    type_action = fields.Selection([
        ('livrer', 'Livrer'),
        ('initier', 'Initier'),
        ('archiver', 'Archiver'),
        ('quit', 'Quit'),
        ('gestion', 'Gestion'),
    ], string="Type d'action")
    department_id = fields.Many2one('hr.department', string="Département")
    month_number = fields.Char(
        string="Month",
        compute="_compute_month_number",
        store=True,
    )
    comment = fields.Text(string="Commentaires")
    validation = fields.Text(string="Validation")

    planned_hours = fields.Float(string="Planned Hours")
    documents_ids = fields.Many2many(
        'ir.attachment', string="Documents",
        help="Documents liés à cette fiche de timesheet"
    )
    documents_count = fields.Integer(string="Nombre de documents", compute="_compute_documents_count", store=True)

    @api.depends('documents_ids')
    def _compute_documents_count(self):
        for line in self:
            line.documents_count = len(line.documents_ids)

    @api.depends('date')
    def _compute_week_number(self):
        for line in self:
            line.week_number = line.date.isocalendar()[1] if line.date else False

    @api.depends('date')
    def _compute_month_number(self):
        for line in self:
            line.month_number = line.date.strftime("%Y-%m") if line.date else False

class AccountMove(models.Model):
    _inherit = 'account.move'

    is_downpayment_invoice = fields.Boolean(
        string="Facture d'acompte",
        help="Cochez cette option si cette facture est un acompte."
    )

    related_invoice_id = fields.Many2one(
        'account.move',
        string="Facture Normale",
        help="Facture normale liée à cet acompte"
    )

    acompte_real_percentage = fields.Float(
        string="Pourcentage réel de l'acompte",
        help="Pourcentage de l'acompte par rapport au total de la facture normale"
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('move_type') == 'out_invoice' and not vals.get('name'):
                seq = self.env['ir.sequence'].next_by_code('account.move') or '/'
                vals['name'] = seq
        return super().create(vals_list)

    def action_force_draft(self):
        """Force le passage en brouillon, même si journal verrouillé ou validation bloquante."""
        for move in self:
            if move.state != 'posted':
                continue  # déjà en brouillon
            move.sudo().write({'state': 'draft'})
            move.sudo().button_draft()

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    sequence_id = fields.Many2one('ir.sequence', string='Sequence for Invoices')
