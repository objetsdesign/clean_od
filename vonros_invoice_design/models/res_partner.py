from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    eori_number = fields.Char(string='EORI Nr')
