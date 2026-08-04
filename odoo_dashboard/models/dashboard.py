# -*- coding: utf-8 -*-
from odoo import models, fields, api


class OdooDashboard(models.Model):
    _name = 'odoo.dashboard'
    _description = "Dashboard Global - Vue d'ensemble des modules"

    name = fields.Char(string="Nom", default="Dashboard Global")

    sales_count = fields.Integer(string="Ventes", compute='_compute_counts')
    purchase_count = fields.Integer(string="Achats", compute='_compute_counts')
    invoice_count = fields.Integer(string="Factures", compute='_compute_counts')
    stock_count = fields.Integer(string="Transferts de stock", compute='_compute_counts')
    mrp_count = fields.Integer(string="Ordres de fabrication", compute='_compute_counts')
    pos_count = fields.Integer(string="Commandes PdV", compute='_compute_counts')
    crm_count = fields.Integer(string="Opportunités CRM", compute='_compute_counts')
    project_count = fields.Integer(string="Tâches Projet", compute='_compute_counts')
    employee_count = fields.Integer(string="Employés", compute='_compute_counts')
    helpdesk_count = fields.Integer(string="Tickets Support", compute='_compute_counts')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_count(self, model_name, domain=None):
        """Retourne le nombre d'enregistrements du modèle, ou 0 si le
        modèle n'existe pas (module non installé) ou en cas d'erreur
        d'accès (droits insuffisants)."""
        domain = domain or []
        if model_name not in self.env:
            return 0
        try:
            return self.env[model_name].sudo().search_count(domain)
        except Exception:
            return 0

    def _safe_action(self, xmlid, fallback_model, name, extra_context=None):
        """Essaie d'ouvrir l'action standard Odoo identifiée par xmlid.
        Si elle n'existe pas, construit une action générique tree/form sur
        fallback_model. Si le modèle lui-même n'existe pas (module non
        installé), affiche une notification plutôt qu'une erreur."""
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
            if extra_context:
                ctx = dict(action.get('context') or {})
                ctx.update(extra_context)
                action['context'] = ctx
            return action
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
                'message': "Le module correspondant à « %s » n'est pas "
                           "installé sur cette base." % name,
                'type': 'warning',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends()
    def _compute_counts(self):
        for rec in self:
            rec.sales_count = rec._safe_count('sale.order')
            rec.purchase_count = rec._safe_count('purchase.order')
            rec.invoice_count = rec._safe_count(
                'account.move', [('move_type', '=', 'out_invoice')])
            rec.stock_count = rec._safe_count('stock.picking')
            rec.mrp_count = rec._safe_count('mrp.production')
            rec.pos_count = rec._safe_count('pos.order')
            rec.crm_count = rec._safe_count('crm.lead')
            rec.project_count = rec._safe_count('project.task')
            rec.employee_count = rec._safe_count('hr.employee')
            rec.helpdesk_count = rec._safe_count('helpdesk.ticket')

    # ------------------------------------------------------------------
    # Actions (boutons du dashboard)
    # ------------------------------------------------------------------
    def action_open_sales(self):
        return self._safe_action('sale.action_orders', 'sale.order', "Ventes")

    def action_open_purchase(self):
        return self._safe_action(
            'purchase.purchase_form_action', 'purchase.order', "Achats")

    def action_open_invoices(self):
        return self._safe_action(
            'account.action_move_out_invoice_type', 'account.move',
            "Factures", extra_context={'default_move_type': 'out_invoice'})

    def action_open_stock(self):
        return self._safe_action(
            'stock.action_picking_tree_all', 'stock.picking',
            "Transferts de stock")

    def action_open_mrp(self):
        return self._safe_action(
            'mrp.mrp_production_action', 'mrp.production',
            "Ordres de fabrication")

    def action_open_pos(self):
        return self._safe_action(
            'point_of_sale.action_pos_pos_form', 'pos.order',
            "Commandes Point de Vente")

    def action_open_crm(self):
        return self._safe_action(
            'crm.crm_lead_all_leads', 'crm.lead', "Opportunités CRM")

    def action_open_project(self):
        return self._safe_action(
            'project.action_view_all_task', 'project.task',
            "Tâches Projet")

    def action_open_employees(self):
        return self._safe_action(
            'hr.open_view_employee_list_my', 'hr.employee', "Employés")

    def action_open_helpdesk(self):
        return self._safe_action(
            'helpdesk.helpdesk_ticket_action_main_tree', 'helpdesk.ticket',
            "Tickets Support")

    def action_refresh(self):
        """Bouton pour forcer le recalcul des compteurs à l'écran."""
        self._compute_counts()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Dashboard actualisé",
                'message': "Les compteurs ont été mis à jour.",
                'type': 'success',
                'sticky': False,
            },
        }
