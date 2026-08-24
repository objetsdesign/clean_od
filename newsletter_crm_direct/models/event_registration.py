from odoo import models, _
from odoo.exceptions import UserError

class EventRegistration(models.Model):
    _inherit = 'event.registration'

    def action_create_crm_lead(self):
        self.ensure_one()

        Lead = self.env['crm.lead']

        # -------------------------------------------------
        # 🔎 CHECK EXISTING LEAD
        # -------------------------------------------------
        existing_lead = Lead.search([
            ('registration_id', '=', self.id)
        ], limit=1)

        if existing_lead:
            raise UserError(_("Une piste CRM existe déjà pour ce participant."))

        # -------------------------------------------------
        # 🏢 TEAM
        # -------------------------------------------------
        team = self.env['crm.team'].search([
            ('name', '=', 'Marketing Leads')
        ], limit=1)

        if not team:
            raise UserError(_("Le pipeline 'Marketing Leads' n'existe pas."))

        # -------------------------------------------------
        # 📌 STAGE
        # -------------------------------------------------
        stage = self.env['crm.stage'].search([
            ('team_id', '=', team.id)
        ], order='sequence asc', limit=1)

        # -------------------------------------------------
        # 🌐 UTM SOURCE = EVENT NAME
        # -------------------------------------------------
        UtmSource = self.env['utm.source']

        source_name = self.event_id.name if self.event_id else False

        source_rec = False
        if source_name:
            source_rec = UtmSource.search([
                ('name', '=', source_name)
            ], limit=1)

            if not source_rec:
                source_rec = UtmSource.create({
                    'name': source_name
                })

        # -------------------------------------------------
        # 📊 LEAD VALUES
        # -------------------------------------------------
        lead_vals = {
            'name': f"{self.event_id.name} - {self.name}",
            'event_id': self.event_id.id,
            'registration_id': self.id,
            'type': 'opportunity',
            'team_id': team.id,
        }

        # stage
        if stage:
            lead_vals['stage_id'] = stage.id

        # partner
        if self.partner_id:
            lead_vals['partner_id'] = self.partner_id.id

        # email / phone
        if self.email:
            lead_vals['email_from'] = self.email
        if self.phone:
            lead_vals['phone'] = self.phone

        # -------------------------------------------------
        # 🎯 SOURCE LINKED TO EVENT
        # -------------------------------------------------
        if source_rec:
            lead_vals['source_id'] = source_rec.id

        # -------------------------------------------------
        # CREATE LEAD
        # -------------------------------------------------
        lead = Lead.create(lead_vals)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Opportunité CRM'),
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': lead.id,
            'target': 'current',
        }