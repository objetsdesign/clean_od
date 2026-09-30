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

# ----------------------------------------------------------------------------
# Arborescence standard créée pour CHAQUE entreprise (VONROSS, ...).
# 'code' = identifiant technique unique par entreprise (permet de régénérer
# l'arborescence sans doublons, même si un dossier a été renommé).
# Adaptez librement cette liste à vos besoins.
# ----------------------------------------------------------------------------
DEFAULT_DOCUMENT_TREE = [
    {'code': 'admin', 'name': "01 - Administration & Juridique", 'children': [
        {'code': 'admin_legal', 'name': "Statuts & Registre de commerce"},
        {'code': 'admin_contracts', 'name': "Contrats"},
        {'code': 'admin_insurance', 'name': "Assurances"},
        {'code': 'admin_mail', 'name': "Courriers officiels"},
    ]},
    {'code': 'finance', 'name': "02 - Finance & Comptabilité", 'children': [
        {'code': 'finance_customer_invoices', 'name': "Factures clients"},
        {'code': 'finance_vendor_bills', 'name': "Factures fournisseurs"},
        {'code': 'finance_bank', 'name': "Banque"},
        {'code': 'finance_tax', 'name': "Fiscalité & Déclarations"},
        {'code': 'finance_statements', 'name': "Bilans & États financiers"},
    ]},
    {'code': 'hr', 'name': "03 - Ressources Humaines", 'children': [
        {'code': 'hr_employees', 'name': "Dossiers employés"},
        {'code': 'hr_payroll', 'name': "Paie"},
        {'code': 'hr_recruitment', 'name': "Recrutement"},
        {'code': 'hr_training', 'name': "Formations"},
        {'code': 'hr_policies', 'name': "Règlement intérieur & Procédures"},
    ]},
    {'code': 'sales', 'name': "04 - Commercial", 'children': [
        {'code': 'sales_quotations', 'name': "Devis & Offres"},
        {'code': 'sales_orders', 'name': "Bons de commande clients"},
        {'code': 'sales_marketing', 'name': "Marketing"},
    ]},
    {'code': 'purchase', 'name': "05 - Achats & Fournisseurs", 'children': [
        {'code': 'purchase_orders', 'name': "Bons de commande fournisseurs"},
        {'code': 'purchase_vendors', 'name': "Fiches fournisseurs"},
    ]},
    {'code': 'projects', 'name': "06 - Projets"},
    {'code': 'technical', 'name': "07 - Technique & Production", 'children': [
        {'code': 'technical_plans', 'name': "Plans & Schémas"},
        {'code': 'technical_procedures', 'name': "Procédures techniques"},
    ]},
    {'code': 'quality', 'name': "08 - Qualité & Conformité", 'children': [
        {'code': 'quality_certifications', 'name': "Certifications"},
        {'code': 'quality_audits', 'name': "Audits"},
    ]},
    {'code': 'archives', 'name': "09 - Archives"},
]

ROOT_CODE = 'root'


class ResCompany(models.Model):
    """ Chaque entreprise possède un dossier racine (portant son nom) qui
    contient toute son arborescence documentaire. """
    _inherit = 'res.company'

    document_root_workspace_id = fields.Many2one(
        'document.workspace', string="Dossier racine des documents",
        readonly=True, copy=False,
        help="Dossier racine de l'arborescence documentaire de l'entreprise.")
    document_folder_count = fields.Integer(
        string="Nb dossiers", compute='_compute_document_folder_count')

    def _compute_document_folder_count(self):
        data = self.env['document.workspace'].sudo()._read_group(
            [('company_id', 'in', self.ids)], ['company_id'], ['__count'])
        mapped = {company.id: count for company, count in data}
        for company in self:
            company.document_folder_count = mapped.get(company.id, 0)

    # ------------------------------------------------------------------
    # Génération de l'arborescence
    # ------------------------------------------------------------------
    def _create_document_tree(self, tree=None):
        """ Crée (ou complète) l'arborescence documentaire de chaque
        entreprise. Idempotent : les dossiers déjà présents (retrouvés par
        leur code système) ne sont ni dupliqués ni renommés. """
        tree = DEFAULT_DOCUMENT_TREE if tree is None else tree
        Workspace = self.env['document.workspace'].sudo()
        for company in self:
            root = Workspace.search([('company_id', '=', company.id),
                                     ('system_code', '=', ROOT_CODE)], limit=1)
            if not root:
                root = Workspace.create({
                    'name': company.name,
                    'company_id': company.id,
                    'system_code': ROOT_CODE,
                    'privacy_visibility': 'employees',
                    'sequence': 0,
                    'description': _("Dossier racine de l'entreprise %s",
                                     company.name),
                })
            if company.document_root_workspace_id != root:
                company.sudo().document_root_workspace_id = root.id
            company._create_document_subtree(root, tree)
        return True

    def _create_document_subtree(self, parent, nodes):
        self.ensure_one()
        Workspace = self.env['document.workspace'].sudo()
        for sequence, node in enumerate(nodes, start=1):
            folder = Workspace.search([('company_id', '=', self.id),
                                       ('system_code', '=', node['code'])],
                                      limit=1)
            if not folder:
                folder = Workspace.create({
                    'name': node['name'],
                    'parent_id': parent.id,
                    'company_id': self.id,
                    'system_code': node['code'],
                    'privacy_visibility': 'employees',
                    'sequence': sequence * 10,
                })
            if node.get('children'):
                self._create_document_subtree(folder, node['children'])

    def _get_document_folder(self, code):
        """ Retourne le dossier système `code` de l'entreprise, en créant
        l'arborescence si nécessaire. """
        self.ensure_one()
        Workspace = self.env['document.workspace'].sudo()
        domain = [('company_id', '=', self.id), ('system_code', '=', code)]
        folder = Workspace.search(domain, limit=1)
        if not folder:
            self._create_document_tree()
            folder = Workspace.search(domain, limit=1)
        return folder

    def action_generate_document_tree(self):
        """ Bouton : (re)génère les dossiers manquants de l'arborescence. """
        self._create_document_tree()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Arborescence documentaire"),
                'message': _("L'arborescence des dossiers est à jour."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_view_document_folders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'enhanced_document_management.document_workspace_action')
        action['domain'] = [('company_id', '=', self.id)]
        action['context'] = {'default_company_id': self.id}
        return action

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._create_document_tree()
        return companies

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            # le dossier racine suit le nom de l'entreprise
            for company in self:
                root = company.sudo().document_root_workspace_id
                if root and root.name != company.name:
                    root.name = company.name
        return res
