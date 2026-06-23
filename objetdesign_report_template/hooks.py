from odoo.api import Environment, SUPERUSER_ID
import logging
_logger = logging.getLogger(__name__)
def assign_partner_sequence_to_existing(env):
    _logger.info("Hook assign_partner_sequence_to_existing is running...")

    seq_customer = env.ref('objetdesign_report_template.sequence_customer')
    seq_supplier = env.ref('objetdesign_report_template.sequence_supplier')

    partners = env['res.partner'].search([
        ('partner_ref', '=', False),
        ('active', '=', True)
    ])

    for partner in partners:
        if partner.supplier_rank > 0:
            partner.partner_ref = seq_supplier.next_by_id()
        elif partner.customer_rank > 0:
            partner.partner_ref = seq_customer.next_by_id()
        else:
            partner.partner_ref = seq_customer.next_by_id()


