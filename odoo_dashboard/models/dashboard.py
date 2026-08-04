# -*- coding: utf-8 -*-
from odoo import models, api

# ----------------------------------------------------------------------
# Configuration centralisée de tous les modules affichés dans le menu
# vertical du dashboard. Pour ajouter un module, il suffit d'ajouter une
# entrée ici : aucune autre modification n'est nécessaire.
# ----------------------------------------------------------------------
MODULES = [
    {
        'key': 'sale', 'label': 'Ventes', 'icon': 'fa-usd', 'color': '#875A7B',
        'model': 'sale.order', 'domain': [], 'xmlid': 'sale.action_orders',
        'fields': ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
    },
    {
        'key': 'purchase', 'label': 'Achats', 'icon': 'fa-shopping-cart', 'color': '#00A09D',
        'model': 'purchase.order', 'domain': [], 'xmlid': 'purchase.purchase_form_action',
        'fields': ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
    },
    {
        'key': 'invoice', 'label': 'Factures', 'icon': 'fa-file-text-o', 'color': '#2C3E50',
        'model': 'account.move', 'domain': [('move_type', '=', 'out_invoice')],
        'xmlid': 'account.action_move_out_invoice_type',
        'fields': ['name', 'partner_id', 'invoice_date', 'amount_total', 'state'],
    },
    {
        'key': 'stock', 'label': 'Stock', 'icon': 'fa-truck', 'color': '#E67E22',
        'model': 'stock.picking', 'domain': [], 'xmlid': 'stock.action_picking_tree_all',
        'fields': ['name', 'partner_id', 'scheduled_date', 'state'],
    },
    {
        'key': 'mrp', 'label': 'Fabrication', 'icon': 'fa-cogs', 'color': '#8E44AD',
        'model': 'mrp.production', 'domain': [], 'xmlid': 'mrp.mrp_production_action',
        'fields': ['name', 'product_id', 'date_planned_start', 'state'],
    },
    {
        'key': 'pos', 'label': 'Point de Vente', 'icon': 'fa-shopping-basket', 'color': '#16A085',
        'model': 'pos.order', 'domain': [], 'xmlid': 'point_of_sale.action_pos_pos_form',
        'fields': ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
    },
    {
        'key': 'crm', 'label': 'CRM / Opportunités', 'icon': 'fa-bullseye', 'color': '#2980B9',
        'model': 'crm.lead', 'domain': [], 'xmlid': 'crm.crm_lead_all_leads',
        'fields': ['name', 'partner_id', 'expected_revenue', 'stage_id'],
    },
    {
        'key': 'project', 'label': 'Projets', 'icon': 'fa-tasks', 'color': '#C0392B',
        'model': 'project.task', 'domain': [], 'xmlid': 'project.action_view_all_task',
        'fields': ['name', 'project_id', 'date_deadline', 'stage_id'],
    },
    {
        'key': 'hr', 'label': 'Employés', 'icon': 'fa-users', 'color': '#27AE60',
        'model': 'hr.employee', 'domain': [], 'xmlid': 'hr.open_view_employee_list_my',
        'fields': ['name', 'job_title', 'department_id', 'work_email'],
    },
    {
        'key': 'helpdesk', 'label': 'Support', 'icon': 'fa-life-ring', 'color': '#D35400',
        'model': 'helpdesk.ticket', 'domain': [], 'xmlid': 'helpdesk.helpdesk_ticket_action_main_tree',
        'fields': ['name', 'partner_id', 'stage_id', 'priority'],
    },
]

FIELD_LABELS = {
    'name': 'Référence', 'partner_id': 'Partenaire', 'date_order': 'Date',
    'invoice_date': 'Date facture', 'scheduled_date': 'Date prévue',
    'date_planned_start': 'Début prévu', 'date_deadline': 'Échéance',
    'amount_total': 'Montant', 'state': 'État', 'stage_id': 'Étape',
    'expected_revenue': 'Revenu attendu', 'job_title': 'Poste',
    'department_id': 'Département', 'work_email': 'Email',
    'priority': 'Priorité', 'project_id': 'Projet', 'product_id': 'Produit',
}


class OdooDashboard(models.Model):
    _name = 'odoo.dashboard'
    _description = "Dashboard Global - Vue d'ensemble des modules"
    # Ce modèle ne stocke aucune donnée : il expose uniquement des méthodes
    # appelées en RPC par le composant JS (OWL) du dashboard.

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------
    def _get_module(self, key):
        return next((m for m in MODULES if m['key'] == key), None)

    def _safe_count(self, model_name, domain=None):
        domain = domain or []
        if model_name not in self.env:
            return 0
        try:
            return self.env[model_name].sudo().search_count(domain)
        except Exception:
            return 0

    def _safe_action(self, xmlid, fallback_model, name):
        try:
            return self.env['ir.actions.act_window']._for_xml_id(xmlid)
        except Exception:
            pass
        if fallback_model in self.env:
            return {
                'type': 'ir.actions.act_window',
                'name': name,
                'res_model': fallback_model,
                'view_mode': 'list,form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Module non installé",
                'message': "Le module correspondant à « %s » n'est pas installé." % name,
                'type': 'warning',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Méthodes appelées depuis le composant JS (OWL)
    # ------------------------------------------------------------------
    @api.model
    def get_modules_config(self):
        """Config du menu vertical (sans données) - un item par module."""
        return [{
            'key': m['key'],
            'label': m['label'],
            'icon': m['icon'],
            'color': m['color'],
            'model': m['model'],
            'installed': m['model'] in self.env,
        } for m in MODULES]

    @api.model
    def get_dashboard_counts(self):
        """Nombre d'enregistrements par module, pour les badges du menu."""
        return {m['key']: self._safe_count(m['model'], m['domain']) for m in MODULES}

    @api.model
    def get_module_records(self, key, limit=12):
        """Retourne les derniers enregistrements d'un module + libellés des
        colonnes, pour affichage dans le tableau de droite."""
        m = self._get_module(key)
        if not m or m['model'] not in self.env:
            return {'records': [], 'field_defs': [], 'installed': False}

        Model = self.env[m['model']].sudo()
        try:
            recs = Model.search_read(m['domain'], m['fields'], limit=limit, order='id desc')
        except Exception:
            return {'records': [], 'field_defs': [], 'installed': True, 'error': True}

        field_defs = [{'name': f, 'label': FIELD_LABELS.get(f, f)} for f in m['fields']]
        return {'records': recs, 'field_defs': field_defs, 'installed': True}

    @api.model
    def get_module_action(self, key):
        """Action complète (liste + formulaire) pour le bouton 'Voir tout'
        et pour l'ouverture d'un enregistrement précis."""
        m = self._get_module(key)
        if not m:
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Erreur', 'message': 'Module inconnu', 'type': 'warning'},
            }
        return self._safe_action(m['xmlid'], m['model'], m['label'])
