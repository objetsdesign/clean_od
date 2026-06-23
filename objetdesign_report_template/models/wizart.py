from odoo import models, fields, api

class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        template = self.env.ref('objetdesign_report_template.email_template_OD', raise_if_not_found=False)
        if template:
            res['mail_template_id'] = template.id

        return res
