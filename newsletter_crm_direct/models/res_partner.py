# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def signup_prepare(self, signup_type='signup', **kwargs):
        """sudo() total pour bypasser crm.lead"""
        return super(ResPartner, self.sudo()).signup_prepare(
            signup_type=signup_type, **kwargs,
        )

    def _compute_opportunity_count(self):
        try:
            return super()._compute_opportunity_count()
        except Exception:
            for rec in self:
                rec.opportunity_count = 0

    def _compute_meeting_count(self):
        try:
            return super()._compute_meeting_count()
        except Exception:
            for rec in self:
                rec.meeting_count = 0

    def _compute_sale_order_count(self):
        try:
            return super()._compute_sale_order_count()
        except Exception:
            for rec in self:
                rec.sale_order_count = 0
