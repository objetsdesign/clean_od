from odoo import models, fields,api

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    registration_id = fields.Many2one(
        'event.registration',
        string='Inscription événement',
        ondelete='cascade'
    )

    _sql_constraints = [
        (
            'unique_registration_lead',
            'unique(registration_id)',
            'Une seule piste est autorisée par participant.'
        )
    ]

    def _sync_source_to_partner(self):
        for lead in self:
            if not lead.partner_id or not lead.source_id:
                continue

            # 🔥 éviter boucle infinie
            if self.env.context.get('skip_source_sync'):
                continue

            lead.partner_id.with_context(
                skip_source_sync=True
            ).write({
                'source_id': lead.source_id.id
            })

    @api.model_create_multi
    def create(self, vals):
        lead = super().create(vals)
        lead._sync_source_to_partner()
        return lead

    def write(self, vals):
        res = super().write(vals)
        self._sync_source_to_partner()
        return res