# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Mruthul Raj(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DocumentWorkspace(models.Model):
    """ Dossier documentaire (workspace) HIÉRARCHIQUE.

    Chaque dossier peut contenir des sous-dossiers (parent_id / child_ids)
    et des documents (document.file.workspace_id), comme un système de
    répertoires :

        VONROSS                         (dossier racine de l'entreprise)
        ├── 01 - Administration & Juridique
        │   ├── Contrats
        │   └── ...
        ├── 02 - Finance & Comptabilité
        │   ├── Factures clients
        │   └── ...
        ├── 03 - Ressources Humaines
        │   └── Dossiers employés
        │       └── Documents - <Employé>
        └── 06 - Projets
            └── Documents - <Projet>
    """
    _name = 'document.workspace'
    _description = 'Document Workspace'
    _inherit = 'mail.thread'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _rec_names_search = ['complete_name', 'name']
    _order = 'complete_name, id'

    name = fields.Char(string='Name', required=True,
                       help="Name of the WorkSpace.")
    display_name = fields.Char(string='Workspace',
                               compute='_compute_display_name',
                               help="Name of the workSpace.")
    # ------------------------------------------------------------------
    # Hiérarchie
    # ------------------------------------------------------------------
    parent_id = fields.Many2one(
        'document.workspace', string="Dossier parent", index=True,
        ondelete='restrict', tracking=True,
        domain="[('company_id', 'in', [company_id, False])]",
        help="Dossier qui contient ce dossier. Laisser vide pour un dossier "
             "racine.")
    child_ids = fields.One2many(
        'document.workspace', 'parent_id', string="Sous-dossiers")
    parent_path = fields.Char(index=True)
    complete_name = fields.Char(
        string="Chemin complet", compute='_compute_complete_name',
        store=True, recursive=True,
        help="Chemin complet du dossier, ex : VONROSS / 02 - Finance / Banque")
    level = fields.Integer(string="Niveau", compute='_compute_level',
                           store=True, recursive=True)
    sequence = fields.Integer(default=10)
    system_code = fields.Char(
        string="Code système", copy=False, readonly=True, index=True,
        help="Identifiant technique des dossiers générés automatiquement "
             "(racine entreprise, RH, Projets...). Ces dossiers ne peuvent "
             "pas être supprimés.")
    is_system = fields.Boolean(string="Dossier système",
                               compute='_compute_is_system', store=True)
    child_count = fields.Integer(string="Nombre de sous-dossiers",
                                 compute='_compute_child_count')
    total_document_count = fields.Integer(
        string="Documents (avec sous-dossiers)",
        compute='_compute_total_document_count')
    color = fields.Integer(string="Couleur")
    # ------------------------------------------------------------------
    company_id = fields.Many2one('res.company', string='Company',
                                 help="WorkSpace belongs to this company",
                                 default=lambda self: self.env.company,
                                 index=True)
    description = fields.Text(string='Description',
                              help="Description about the workSpace")
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", copy=False, readonly=True,
        help="Si renseigné, cet espace est le dossier personnel de cet employé : "
             "lui seul (et les Managers) peut y accéder.")
    project_id = fields.Many2one(
        'project.project', string="Projet", copy=False, readonly=True,
        help="Si renseigné, cet espace est le dossier de ce projet : "
             "seuls les membres/abonnés du projet (et les Managers) peuvent y accéder.")
    document_count = fields.Integer(compute='_compute_document_count',
                                    string='Document Count',
                                    help="Number of documents uploaded "
                                         "under this workSpace")
    privacy_visibility = fields.Selection([
        ('followers', 'Invited internal users (private)'),
        ('employees', 'All internal users'), ],
        string='Visibility', required=True,
        default='employees',
        help='- Invited internal users: when following a workspace, internal '
             'users will get access to all of its documents without '
             'distinction \n\n'
             'All internal users: all internal users can access the '
             'workspace and all of its documents without distinction.\n\n')
    google_drive_folder_id = fields.Char(
        string='Google drive folder id',
        help='Id of workspace in google drive if created',
        copy=False, readonly=True)
    onedrive_folder_id = fields.Char(
        string='One drive folder id',
        help='Id of workspace in one drive if created',
        copy=False, readonly=True)

    _sql_constraints = [
        ('system_code_company_uniq', 'unique(company_id, system_code)',
         "Un dossier système avec ce code existe déjà pour cette entreprise."),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for workspace in self:
            if workspace.parent_id:
                workspace.complete_name = '%s / %s' % (
                    workspace.parent_id.complete_name, workspace.name)
            else:
                workspace.complete_name = workspace.name

    @api.depends('parent_id.level')
    def _compute_level(self):
        for workspace in self:
            workspace.level = (workspace.parent_id.level + 1
                               if workspace.parent_id else 0)

    @api.depends('system_code')
    def _compute_is_system(self):
        for workspace in self:
            workspace.is_system = bool(workspace.system_code)

    @api.depends_context('hierarchical_naming')
    @api.depends('name', 'complete_name')
    def _compute_display_name(self):
        """ Chemin complet partout (champs many2one, listes...), mais nom
        court dans le panneau latéral (search panel) qui affiche déjà
        l'arbre : Odoo y passe hierarchical_naming=False. """
        hierarchical = self.env.context.get('hierarchical_naming', True)
        for workspace in self:
            workspace.display_name = (
                workspace.complete_name if hierarchical else workspace.name
            ) or workspace.name

    def _compute_child_count(self):
        data = self.env['document.workspace']._read_group(
            [('parent_id', 'in', self.ids)], ['parent_id'], ['__count'])
        mapped = {parent.id: count for parent, count in data}
        for workspace in self:
            workspace.child_count = mapped.get(workspace.id, 0)

    def _compute_document_count(self):
        """
        Calculate the number of documents associated with this workspace
        (documents directly inside the folder).
        """
        data = self.env['document.file']._read_group(
            [('workspace_id', 'in', self.ids)], ['workspace_id'], ['__count'])
        mapped = {ws.id: count for ws, count in data}
        for record in self:
            record.document_count = mapped.get(record.id, 0)

    def _compute_total_document_count(self):
        """ Nombre de documents du dossier ET de tous ses sous-dossiers. """
        DocumentFile = self.env['document.file']
        for record in self:
            record.total_document_count = DocumentFile.search_count(
                [('workspace_id', 'child_of', record.id)]) if record.id else 0

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(
                _("Un dossier ne peut pas être placé dans lui-même ou dans "
                  "un de ses sous-dossiers."))

    @api.constrains('parent_id', 'company_id')
    def _check_parent_company(self):
        for workspace in self:
            parent = workspace.parent_id
            if parent and parent.company_id and \
                    parent.company_id != workspace.company_id:
                raise ValidationError(_(
                    "Le dossier « %(child)s » doit appartenir à la même "
                    "entreprise que son dossier parent « %(parent)s » "
                    "(%(company)s).",
                    child=workspace.name, parent=parent.complete_name,
                    company=parent.company_id.name))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.onchange('parent_id')
    def _onchange_parent_id(self):
        if self.parent_id and self.parent_id.company_id:
            self.company_id = self.parent_id.company_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Un sous-dossier hérite toujours de l'entreprise de son parent
            if vals.get('parent_id'):
                parent = self.browse(vals['parent_id'])
                if parent.company_id:
                    vals['company_id'] = parent.company_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('parent_id') and 'company_id' not in vals:
            parent = self.browse(vals['parent_id'])
            if parent.company_id:
                vals['company_id'] = parent.company_id.id
        res = super().write(vals)
        if 'company_id' in vals:
            # propage l'entreprise à toute la descendance
            descendants = self.search([
                ('id', 'child_of', self.ids), ('id', 'not in', self.ids),
                ('company_id', '!=', vals['company_id'])])
            if descendants:
                descendants.write({'company_id': vals['company_id']})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_system_or_not_empty(self):
        for workspace in self:
            if workspace.system_code and \
                    not self.env.context.get('force_delete_system_folder'):
                raise UserError(_(
                    "Le dossier « %s » est un dossier système de "
                    "l'arborescence et ne peut pas être supprimé "
                    "(vous pouvez le renommer).", workspace.complete_name))
            if workspace.child_ids:
                raise UserError(_(
                    "Le dossier « %s » contient des sous-dossiers : "
                    "supprimez-les ou déplacez-les d'abord.",
                    workspace.complete_name))

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        if not (default or {}).get('name'):
            for workspace, vals in zip(self, vals_list):
                vals['name'] = _("%s (copie)", workspace.name)
        return vals_list

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def button_view_document(self):
        """
        Open the Kanban view of the documents of this folder AND of all its
        sub-folders. New documents are created in this folder.
        :return: Action to open the Kanban view
        """
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'enhanced_document_management.document_file_action')
        action.update({
            'name': self.complete_name,
            'domain': [('workspace_id', 'child_of', self.id)],
            'context': {'default_workspace_id': self.id},
        })
        return action

    def action_view_subfolders(self):
        """ Ouvre la liste des sous-dossiers directs. """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.workspace',
            'name': _("Sous-dossiers de %s", self.complete_name),
            'view_mode': 'list,form,hierarchy',
            'domain': [('parent_id', '=', self.id)],
            'context': {'default_parent_id': self.id,
                        'default_company_id': self.company_id.id},
        }

    def action_create_subfolder(self):
        """ Formulaire de création d'un sous-dossier dans ce dossier. """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.workspace',
            'name': _("Nouveau sous-dossier"),
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_parent_id': self.id,
                        'default_company_id': self.company_id.id,
                        'default_privacy_visibility':
                            self.privacy_visibility},
        }
