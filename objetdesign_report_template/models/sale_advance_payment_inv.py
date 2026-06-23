from odoo import models

class SaleAdvancePaymentInvInherit(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def create_invoices(self):
        """Créer les factures d'acompte ou de livraison tout en conservant le pourcentage et le montant d'acompte d'origine."""
        res = super(SaleAdvancePaymentInvInherit, self).create_invoices()

        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')

        if active_model == 'sale.order' and active_id:
            sale_order = self.env[active_model].browse(active_id)
            invoice = sale_order.invoice_ids.filtered(lambda inv: inv.state == 'draft')[:1]

            if not invoice:
                return res

            lang = (self.env.user.lang or sale_order.partner_id.lang or 'fr_FR').lower()

            term = 'down payment' if 'en' in lang else 'acompte'
            label = 'Down Payment' if 'en' in lang else 'Acompte'

            if self.advance_payment_method == 'percentage':
                invoice.acompte_amount = self.amount
                for line in invoice.invoice_line_ids:
                    if term in (line.name or '').lower():
                        if 'en' in lang:
                            line.name = f"{label} of {self.amount:.2f} %"
                        else:
                            line.name = f"{label} de {self.amount:.2f} %"
                        break

            elif self.advance_payment_method == 'delivered':
                invoice.acompte_amount = self.amount
                for line in invoice.invoice_line_ids:
                    if term in (line.name or '').lower():
                        if 'en' in lang:
                            line.name = f"{label} of {self.amount:.2f} %"
                        else:
                            line.name = f"{label} de {self.amount:.2f} %"
                        break

        return res
