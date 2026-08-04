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
        # Modèle de ligne utilisé pour donner un vrai montant au document
        # via le mini sélecteur Produit + Prix (le total est calculé par
        # Odoo à partir des lignes, jamais saisi directement).
        'line_model': 'sale.order.line', 'line_order_field': 'order_id',
        'line_qty_field': 'product_uom_qty',
    },
    {
        'key': 'purchase', 'label': 'Achats', 'icon': 'fa-shopping-cart', 'color': '#00A09D',
        'model': 'purchase.order', 'domain': [], 'xmlid': 'purchase.purchase_form_action',
        'fields': ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
        'line_model': 'purchase.order.line', 'line_order_field': 'order_id',
        'line_qty_field': 'product_qty',
    },
    {
        'key': 'invoice', 'label': 'Factures', 'icon': 'fa-file-text-o', 'color': '#2C3E50',
        'model': 'account.move', 'domain': [('move_type', '=', 'out_invoice')],
        'xmlid': 'account.action_move_out_invoice_type',
        'fields': ['name', 'partner_id', 'invoice_date', 'amount_total', 'state'],
        # account_id sur la ligne est un champ calculé (compte comptable du
        # produit ou du journal), rempli automatiquement par Odoo dès que
        # product_id + move_id sont renseignés : pas besoin de le fournir.
        'line_model': 'account.move.line', 'line_order_field': 'move_id',
        'line_qty_field': 'quantity',
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
        'line_model': 'pos.order.line', 'line_order_field': 'order_id',
        'line_qty_field': 'qty',
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

    def _domain_defaults(self, domain):
        """Extrait les égalités simples d'un domaine (ex: [('move_type','=',
        'out_invoice')]) pour les injecter comme valeurs par défaut à la
        création. Sans cela, une facture créée depuis la ligne rapide serait
        enregistrée comme simple écriture comptable et n'apparaîtrait jamais
        dans la liste (filtrée sur move_type='out_invoice')."""
        defaults = {}
        for cond in (domain or []):
            if isinstance(cond, (list, tuple)) and len(cond) == 3 and cond[1] == '=':
                defaults[cond[0]] = cond[2]
        return defaults

    def _extra_create_defaults(self, m):
        """Valeurs par défaut supplémentaires, non déductibles du domaine
        d'affichage, nécessaires pour que la création directe (sans passer
        par les onchange du formulaire complet) satisfasse les champs
        obligatoires d'Odoo. Concerne surtout stock.picking et
        mrp.production, qui exigent un type d'opération et des
        emplacements/UdM habituellement déduits automatiquement par le
        formulaire."""
        extra = {}
        try:
            if m['key'] == 'stock' and 'stock.picking.type' in self.env:
                picking_type = self.env['stock.picking.type'].sudo().search(
                    [('code', '=', 'outgoing')], limit=1)
                if picking_type:
                    extra['picking_type_id'] = picking_type.id
                    src = picking_type.default_location_src_id \
                        or picking_type.warehouse_id.lot_stock_id \
                        or self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
                    dest = picking_type.default_location_dest_id \
                        or self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
                    if src:
                        extra['location_id'] = src.id
                    if dest:
                        extra['location_dest_id'] = dest.id

            elif m['key'] == 'mrp' and 'stock.picking.type' in self.env:
                picking_type = self.env['stock.picking.type'].sudo().search(
                    [('code', '=', 'mrp_operation')], limit=1)
                if picking_type:
                    extra['picking_type_id'] = picking_type.id
        except Exception:
            return {}
        return extra

    # ------------------------------------------------------------------
    # Méthodes appelées depuis le composant JS (OWL)
    # ------------------------------------------------------------------
    @api.model
    def get_modules_config(self):
        """Config du menu vertical (sans données) - un item par module."""
        result = []
        for m in MODULES:
            line_model = m.get('line_model')
            has_lines = bool(line_model and line_model in self.env)
            create_defaults = self._domain_defaults(m['domain'])
            create_defaults.update(self._extra_create_defaults(m))
            result.append({
                'key': m['key'],
                'label': m['label'],
                'icon': m['icon'],
                'color': m['color'],
                'model': m['model'],
                'installed': m['model'] in self.env,
                'lineModel': line_model if has_lines else None,
                'lineOrderField': m.get('line_order_field') if has_lines else None,
                'lineQtyField': m.get('line_qty_field') if has_lines else None,
                'createDefaults': create_defaults,
            })
        return result

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

    @api.model
    def get_module_field_specs(self, key):
        """Métadonnées des champs (type, relation, lecture seule, options de
        sélection...) utilisées côté JS pour construire les cases de saisie
        des lignes d'ajout et d'édition rapide directement dans le tableau."""
        m = self._get_module(key)
        if not m or m['model'] not in self.env:
            return []

        Model = self.env[m['model']].sudo()
        try:
            infos = Model.fields_get(
                m['fields'],
                attributes=['type', 'string', 'relation', 'selection', 'required', 'readonly'])
        except Exception:
            return []

        specs = []
        for fname in m['fields']:
            info = infos.get(fname, {})
            specs.append({
                'name': fname,
                'label': FIELD_LABELS.get(fname, info.get('string', fname)),
                'type': info.get('type', 'char'),
                'relation': info.get('relation'),
                'selection': info.get('selection') if info.get('type') == 'selection' else None,
                'required': bool(info.get('required')),
                'readonly': bool(info.get('readonly')),
            })
        return specs
