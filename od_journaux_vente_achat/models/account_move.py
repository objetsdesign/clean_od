from odoo import api, models


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.depends("company_id", "invoice_filter_type_domain", "move_type")
    def _compute_suitable_journal_ids(self):
        super()._compute_suitable_journal_ids()
        Journal = self.env["account.journal"]
        for move in self.filtered(lambda m: m.move_type == "entry"):
            company = move.company_id or self.env.company
            if hasattr(Journal, "_check_company_domain"):
                company_domain = Journal._check_company_domain(company)
            else:
                company_domain = [("company_id", "=", company.id)]
            move.suitable_journal_ids |= Journal.search(
                company_domain + [("type", "in", ("sale", "purchase"))]
            )
