# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import fields, models


class HrPayslipRun(models.Model):
    _name = "hr.payslip.run"
    _description = "Payslip Batches"

    name = fields.Char(required=True)
    slip_ids = fields.One2many(
        "hr.payslip",
        "payslip_run_id",
        string="Payslips",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("close", "Close")],
        string="Status",
        index=True,
        readonly=True,
        copy=False,
        default="draft",
    )
    date_start = fields.Date(
        string="Date From",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_end = fields.Date(
        string="Date To",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
        + relativedelta(months=+1, day=1, days=-1),
    )
    credit_note = fields.Boolean(
        string="Credit Note",
        help="If its checked, indicates that all payslips generated from here "
        "are refund payslips.",
    )

    def draft_payslip_run(self):
        return self.write({"state": "draft"})

    def close_payslip_run(self):
        return self.write({"state": "close"})
