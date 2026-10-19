from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_name_invoice_report(self):
        """Utilise le design Von Ros uniquement pour les factures de la société Von Ros."""
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund') and self.company_id._is_vonros():
            return 'vonros_invoice_design.report_invoice_document_vonros'
        return super()._get_name_invoice_report()
