from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    logo_footer = fields.Binary("Logo Footer")
