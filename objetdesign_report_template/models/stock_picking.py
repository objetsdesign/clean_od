
from odoo import models, fields

class StockPickingInfo(models.Model):
    _name = "stock.picking.info"
    _description = "Informations complémentaires pour le picking"

    picking_id = fields.Many2one('stock.picking', string="Livraison", required=True, ondelete='cascade')
    ref_shipping_mark = fields.Char(string="Ref Shipping Mark")
    designation = fields.Text(string="Désignation")
    qty = fields.Char(string="Quantité")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    info_line_ids = fields.One2many('stock.picking.info', 'picking_id', string="Informations supplémentaires")
    marquage_carton_shipping = fields.Text('Marquage Carton.Shipping mark')
