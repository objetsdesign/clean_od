# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ged_document_ids = fields.One2many(
        'ged.document', 'employee_id', string="Documents GED"
    )
    ged_document_count = fields.Integer(
        string="Nb documents", compute='_compute_ged_document_count'
    )

    def _compute_ged_document_count(self):
        grouped = self.env['ged.document']._read_group(
            [('employee_id', 'in', self.ids)],
            ['employee_id'], ['__count']
        )
        counts = {employee.id: count for employee, count in grouped}
        for emp in self:
            emp.ged_document_count = counts.get(emp.id, 0)

    def action_view_ged_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ged_management.action_ged_document'
        )
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {
            'default_employee_id': self.id,
            'search_default_employee_id': self.id,
        }
        return action
