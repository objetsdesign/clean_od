import html
import re

from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_name_invoice_report(self):
        """Utilise le design Von Ros uniquement pour les factures de la société Von Ros."""
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund') and self.company_id._is_vonros():
            return 'vonros_facture_excel.report_invoice_document_vonros'
        return super()._get_name_invoice_report()

    def _vr_observations(self):
        """Observations en texte simple (sans balises ni CSS caché qui casserait la mise en page)."""
        self.ensure_one()
        src = str(self.narration or '')
        src = re.sub(r'(?is)<(style|script|head)\b.*?</\1>', ' ', src)
        src = re.sub(r'(?s)<[^>]+>', ' ', src)
        return ' '.join(html.unescape(src).split())
