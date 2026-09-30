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
from . import controllers
from . import models
from . import wizards


def setup_document_hierarchy(env):
    """ Crée l'arborescence documentaire de chaque entreprise (dossier racine
    + sous-dossiers standard) puis range les dossiers employés et projets
    existants dans « RH / Dossiers employés » et « Projets ». Idempotent. """
    companies = env['res.company'].sudo().search([])
    companies._create_document_tree()
    Workspace = env['document.workspace'].sudo()
    for code, field in (('hr_employees', 'employee_id'),
                        ('projects', 'project_id')):
        workspaces = Workspace.search([(field, '!=', False),
                                       ('parent_id', '=', False)])
        for workspace in workspaces:
            company = workspace.company_id or workspace[field].company_id \
                or env.company
            workspace.write({
                'company_id': company.id,
                'parent_id': company._get_document_folder(code).id,
            })


def post_init_hook(env):
    """ Crée rétroactivement le dossier personnel de chaque employé et le
    dossier de chaque projet déjà existants au moment de l'installation/
    mise à jour du module. Garantit aussi que tout utilisateur interne
    existant possède bien le groupe 'Document Management / User' (le
    manifest ne l'ajoute automatiquement qu'aux NOUVEAUX utilisateurs
    créés après l'installation, pas aux comptes déjà existants). """
    group_user = env.ref('enhanced_document_management.view_own_document')
    group_manager = env.ref('enhanced_document_management.view_all_document')
    internal_users = env['res.users'].search([('share', '=', False)])
    for res_user in internal_users:
        if group_manager.id not in res_user.groups_id.ids \
                and group_user.id not in res_user.groups_id.ids:
            res_user.write({'groups_id': [(4, group_user.id)]})

    setup_document_hierarchy(env)

    employees = env['hr.employee'].search([('document_workspace_id', '=', False)])
    for employee in employees:
        employee._create_document_workspace()

    projects = env['project.project'].search([('document_workspace_id', '=', False)])
    for project in projects:
        project._create_document_workspace()
