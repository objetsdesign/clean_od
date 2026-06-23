from datetime import timedelta

from odoo import models, fields, api, _
import logging
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class CrmLeadInherit(models.Model):
    _inherit = "crm.lead"
    sale_order_id = fields.Many2one(
        'sale.order',
        string="Commande client",
        readonly=True
    )

    invoice_id = fields.Many2one(
        'account.move',
        string="Facture",
        readonly=True
    )

    is_prospect_lead = fields.Boolean(
        string="Prospect",
        compute="_compute_is_prospect_lead",
        store=False
    )
    sector_activity_id = fields.Many2one(
        'sector.activity',
        string="Secteur d'activité",
        store=False,
        readonly=False
    )
    partner_type = fields.Selection([
        ('B2B', 'B2B'),
        ('B2C', 'B2C')
    ], string="Type Client", compute='_compute_partner_type', store=False)
    product_id = fields.Many2one(
        'product.product',
        string="Produit à fabriquer",
        domain="[('type', 'in', ['product', 'consu'])]"
    )

    mo_id = fields.Many2one(
        'mrp.production',
        string="Ordre de fabrication",
        readonly=True
    )
    sale_order_ids = fields.One2many('sale.order', 'opportunity_id', string="Devis liés")
    total_cost = fields.Monetary(
        string="Coût total",
        compute='_compute_margin',
        store=False,
        currency_field='company_currency_id'
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Devise société',
        default=lambda self: self.env.company.currency_id
    )

    total_margin = fields.Monetary(
        string="Marge totale",
        compute='_compute_margin',
        store=False,
        currency_field='company_currency_id'
    )

    margin_percent = fields.Float(
        string="Marge (%)",
        compute='_compute_margin',
        store=False
    )

    def action_next_stage(self):
        """Avancer au stage suivant dans le pipeline existant"""
        stage_names = ["Nouvelle demande de devis", "Contact initial", "Démonstration", "Devis envoyé", "Négociation",
                       "Clôture"]
        for lead in self:
            if not lead.stage_id:
                continue
            current_stage_name = lead.stage_id.name
            if current_stage_name in stage_names:
                index = stage_names.index(current_stage_name)
                if index + 1 < len(stage_names):
                    next_stage_name = stage_names[index + 1]
                    next_stage = self.env['crm.stage'].search([('name', '=', next_stage_name)], limit=1)
                    if next_stage:
                        lead.stage_id = next_stage.id

    @api.depends('sale_order_ids.order_line.price_unit',
                 'sale_order_ids.order_line.product_uom_qty',
                 'sale_order_ids.order_line.product_id.standard_price')
    def _compute_margin(self):
        for lead in self.sudo():
            total_cost = 0
            total_price = 0
            for order in lead.sale_order_ids:
                for line in order.order_line:
                    cost = line.product_id.standard_price * line.product_uom_qty
                    price = line.price_unit * line.product_uom_qty * (1 - (line.discount or 0.0) / 100)
                    total_cost += cost
                    total_price += price
            lead.total_margin = total_price - total_cost
            lead.total_cost = total_cost
            lead.margin_percent = ((total_price - total_cost) / total_price * 100) if total_price else 0

    def action_open_invoice_form(self):
        self.ensure_one()

        if self.type != 'opportunity':
            raise UserError(_("La facturation est disponible uniquement pour une opportunité."))

        if not self.partner_id:
            raise UserError(_("Veuillez sélectionner un client."))

        if not self.product_id:
            raise UserError(_("Veuillez sélectionner un produit ou service."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Facture client'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_move_type': 'out_invoice',
                'default_partner_id': self.partner_id.id,
                'default_invoice_origin': self.name,
                'default_invoice_line_ids': [(0, 0, {
                    'product_id': self.product_id.id,
                    'quantity': 1,
                    'price_unit': self.product_id.list_price,
                    'name': self.product_id.name,
                })],
            }
        }

    def action_create_mo_from_crm(self):
        self.ensure_one()

        if self.type != 'opportunity':
            raise UserError(_("La fabrication est autorisée uniquement pour une opportunité."))

        if not self.product_id:
            raise UserError(_("Veuillez sélectionner un produit à fabriquer."))

        product = self.product_id

        if not product.bom_ids:
            raise UserError(_("Ce produit n'a pas de nomenclature de fabrication."))

        return ({
            'type': 'ir.actions.act_window',
            'name': _('Ordre de fabrication'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_product_id': product.id,
                'default_product_qty': 1,
                'default_product_uom_id': product.uom_id.id,
                'default_origin': self.name,
                'default_company_id': self.company_id.id,
                'default_lead_id': self.id,
            }
        })

    @api.depends('partner_id', 'partner_id.category_id', 'partner_id.category_id.name')
    def _compute_partner_type(self):
        for lead in self.sudo():
            if not lead.partner_id:
                lead.partner_type = False
                continue
            categories = lead.partner_id.category_id.mapped('name')
            if 'B2B' in categories:
                lead.partner_type = 'B2B'
            elif 'B2C' in categories:
                lead.partner_type = 'B2C'
            else:
                lead.partner_type = False

    def get_all_leads_global(self):
        domain = [
            ('country_id', '!=', False),
            ('source_id', '!=', False),
            ('stage_id', '!=', False),
        ]
        return self.sudo().search(domain)

    def action_set_stage(self, stage_name):
        """Change le stage vers le nom donné"""
        CrmStage = self.env['crm.stage'].sudo()
        CrmTeam = self.env['crm.team'].sudo()

        lead_team = CrmTeam.search([('name', '=', 'Leads')], limit=1)
        if not lead_team:
            lead_team = CrmTeam.create({'name': 'Leads'})

        stage = CrmStage.search([
            ('name', '=', stage_name),
            ('team_id', '=', False)
        ], limit=1)

        if not stage:
            stage = CrmStage.create({'name': stage_name, 'team_id': False, 'sequence': 1})

        self.write({'stage_id': stage.id, 'team_id': lead_team.id})
        return True

    def action_convert_to_opportunity(self):
        for lead in self:
            if lead.type == 'opportunity':
                continue

            lead.write({
                'type': 'opportunity',
                'date_conversion': fields.Datetime.now(),
            })

        return True

    def action_set_lead(self):
        return self.action_set_stage('Leads')

    def action_set_prospect(self):
        return self.action_set_stage('Prospects')

    def action_set_pro(self):
        return self.action_set_stage('Pro')

    def action_set_vip(self):
        return self.action_set_stage('VIP')

    def action_set_partenaire(self):
        return self.action_set_stage('Partenaires')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('partner_id'):
                partner = self.env['res.partner'].sudo().browse(vals['partner_id'])
                if partner.source_id:
                    vals['source_id'] = partner.source_id.id
                    _logger.info(
                        "📥 Source CRM défini depuis Partner (create): %s",
                        partner.source_id.name
                    )
                if partner.sector_activity_id:
                    vals['sector_activity_id'] = partner.sector_activity_id.id
                    _logger.info(
                        "📥 Secteur CRM rempli depuis Partner (create): %s",
                        partner.sector_activity_id.name
                    )

            if not vals.get('source_id'):
                raw_source = vals.get('utm_source') or self.env.context.get('utm_source') or vals.get('source')
                if raw_source:
                    source = self.env['utm.source'].sudo().search(
                        [('name', 'ilike', raw_source)], limit=1
                    )
                    if source:
                        vals['source_id'] = source.id

        return super().create(vals_list)

    def write(self, vals):

        if 'partner_id' in vals:
            partner = self.env['res.partner'].sudo().browse(vals['partner_id'])
            if partner.source_id:
                vals['source_id'] = partner.source_id.id
            if partner.sector_activity_id:
                vals['sector_activity_id'] = partner.sector_activity_id.id

        old_stages = {lead.id: lead.stage_id for lead in self}

        res = super().write(vals)

        if 'stage_id' in vals:
            for lead in self:
                old_stage = old_stages.get(lead.id)
                if old_stage != lead.stage_id:
                    lead._create_stage_activity(old_stage, lead.stage_id)

        return res

    def _create_stage_activity(self, old_stage, new_stage):
        """Créer une activité lors du changement de stage"""
        self.ensure_one()

        activity_type = self.env.ref('mail.mail_activity_data_todo')

        summary = _("Changement de statut CRM")
        note = _(
            "Le pipeline est passé de <b>%s</b> à <b>%s</b>."
        ) % (
                   old_stage.name if old_stage else _('Non défini'),
                   new_stage.name
               )

        self.activity_schedule(
            activity_type_id=activity_type.id,
            summary=summary,
            note=note,
            user_id=self.user_id.id or self.env.user.id,
            date_deadline=fields.Date.today() + timedelta(days=1),
        )

    @api.depends('stage_id')
    def _compute_is_prospect_lead(self):
        for lead in self.sudo():
            if lead.stage_id.is_prospect_stage:
                lead.is_prospect_lead = False
            else:
                lead.is_prospect_lead = True

class CrmStage(models.Model):
    _inherit = "crm.stage"

    is_prospect_stage = fields.Boolean(default=False)
