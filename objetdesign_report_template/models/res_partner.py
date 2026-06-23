from odoo import models, fields, api

class PartnerBudgetFournisseur(models.Model):
    _inherit = "res.partner"

    partner_type = fields.Selection([
        ('customer', 'Client'),
        ('supplier', 'Fournisseur'),
    ], string="Type de partenaire")
    partner_ref = fields.Char(string='Référence', readonly=True, copy=False)

    @api.onchange('partner_type')
    def _onchange_partner_type(self):
        for partner in self:
            if partner.partner_type == 'customer':
                partner.customer_rank = 1
                partner.supplier_rank = 0
            elif partner.partner_type == 'supplier':
                partner.customer_rank = 0
                partner.supplier_rank = 1

    @api.model_create_multi
    def create(self, vals_list):
        seq_customer = self.env.ref('objetdesign_report_template.sequence_customer')
        seq_supplier = self.env.ref('objetdesign_report_template.sequence_supplier')

        for vals in vals_list:
            if not vals.get('partner_type'):
                if vals.get('customer_rank', 0) > 0:
                    vals['partner_type'] = 'customer'
                elif vals.get('supplier_rank', 0) > 0:
                    vals['partner_type'] = 'supplier'
                else:
                    vals['partner_type'] = 'customer'
                    vals['customer_rank'] = 1
                    vals['supplier_rank'] = 0

            if not vals.get('partner_ref'):
                if vals['partner_type'] == 'customer':
                    vals['partner_ref'] = seq_customer.next_by_id()
                elif vals['partner_type'] == 'supplier':
                    vals['partner_ref'] = seq_supplier.next_by_id()

        return super().create(vals_list)

    def write(self, vals):
        seq_customer = self.env.ref('objetdesign_report_template.sequence_customer')
        seq_supplier = self.env.ref('objetdesign_report_template.sequence_supplier')

        for partner in self:
            if vals.get('partner_type'):
                new_type = vals['partner_type']
                old_ref = partner.partner_ref or ''

                number_part = ''.join([c for c in old_ref if c.isdigit()])

                if not number_part:
                    if new_type == 'customer':
                        number_part = seq_customer.next_by_id().lstrip('CUST')
                    elif new_type == 'supplier':
                        number_part = seq_supplier.next_by_id().lstrip('SUPP')

                if new_type == 'customer':
                    partner.partner_ref = 'CUST' + number_part
                    partner.customer_rank = 1
                    partner.supplier_rank = 0
                elif new_type == 'supplier':
                    partner.partner_ref = 'SUPP' + number_part
                    partner.customer_rank = 0
                    partner.supplier_rank = 1

        return super().write(vals)
