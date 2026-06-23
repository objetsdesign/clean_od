from odoo import models, fields, api, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class ProductsTemplate(models.Model):
    _inherit = 'product.template'

    x_matiere = fields.Char(string="Matière")
    x_dimensions = fields.Char(string="Dimensions")
    x_marquage = fields.Char(string="Marquage")
    x_conditionnement = fields.Char(string="Conditionnement")
    x_etiquette = fields.Char(string="Etiquette")
    x_color = fields.Char(string="Color")
    x_infos = fields.Text(string="Infos supplémentaires")
    x_frais_tech = fields.Float(string="Frais Technique")
