from odoo import models

VONROS_TEMPLATE = 'vonros_invoice_design.report_invoice_document_vonros'
INVOICE_REPORTS = ('account.report_invoice', 'account.report_invoice_with_payments')


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def get_paperformat(self):
        if self.env.context.get('vonros_paperformat'):
            paperformat = self.env.ref('vonros_invoice_design.paperformat_vonros', raise_if_not_found=False)
            if paperformat:
                return paperformat
        return super().get_paperformat()

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Format papier Von Ros (marges Excel) seulement si toutes les factures imprimées sont Von Ros."""
        report = self._get_report(report_ref)
        if res_ids and report.report_name in INVOICE_REPORTS:
            ids = [res_ids] if isinstance(res_ids, int) else res_ids
            moves = self.env['account.move'].browse(ids).exists()
            if moves and all(m._get_name_invoice_report() == VONROS_TEMPLATE for m in moves):
                self = self.with_context(vonros_paperformat=True)
        return super(IrActionsReport, self)._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
