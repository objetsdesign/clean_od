# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    customization_id = fields.Many2one(
        'product.customization', string="Personnalisation", copy=False,
        ondelete='set null')
    customization_preview = fields.Image(
        string="Aperçu perso", related='customization_id.preview_image')
    customization_extra_price = fields.Float(
        string="Supplément personnalisation",
        related='customization_id.extra_price', store=True)

    def _get_display_price(self):
        """Ajoute le supplément de personnalisation au prix de base."""
        price = super()._get_display_price()
        if self.customization_id:
            price += self.customization_id.extra_price
        return price

    def _get_protected_fields(self):
        return super()._get_protected_fields() + ['customization_id']

    @api.depends('customization_id')
    def _compute_name_short(self):
        # hook éventuel : afficher un marqueur "personnalisé" dans les rapports
        return

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.customization_id:
            res['name'] = (res.get('name') or '') + "\n(Produit personnalisé : %s)" % (
                self.customization_id.name)
        return res
