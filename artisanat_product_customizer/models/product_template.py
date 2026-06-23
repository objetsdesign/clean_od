# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_customizable = fields.Boolean(
        string="Produit personnalisable",
        help="Affiche le configurateur de personnalisation sur la fiche produit.")

    customization_area_ids = fields.One2many(
        'product.customization.area', 'product_tmpl_id',
        string="Zones de personnalisation")

    customization_font_ids = fields.Many2many(
        'product.customization.font', string="Polices proposées")
    customization_color_ids = fields.Many2many(
        'product.customization.color', string="Couleurs proposées")
    customization_clipart_ids = fields.Many2many(
        'product.customization.clipart', string="Cliparts proposés")

    customization_base_price = fields.Float(
        string="Frais de personnalisation",
        help="Supplément forfaitaire ajouté dès qu'une personnalisation est créée.")

    customization_text_price = fields.Float(
        string="Prix par texte ajouté", default=0.0)
    customization_image_price = fields.Float(
        string="Prix par image ajoutée", default=0.0)

    customization_area_count = fields.Integer(
        string="Nb de zones", compute='_compute_customization_area_count')

    @api.depends('customization_area_ids')
    def _compute_customization_area_count(self):
        for tmpl in self:
            tmpl.customization_area_count = len(tmpl.customization_area_ids)

    def get_customizer_config(self):
        """Sérialise toute la configuration utile au configurateur frontend."""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        areas = []
        for area in self.customization_area_ids:
            img_url = (
                '/web/image/product.customization.area/%s/background_image' % area.id
                if area.background_image
                else '/web/image/product.template/%s/image_1024' % self.id
            )
            areas.append({
                'id': area.id,
                'name': area.name,
                'image_url': img_url,
                'box': {
                    'left': area.pos_left,
                    'top': area.pos_top,
                    'width': area.pos_width,
                    'height': area.pos_height,
                },
                'allow_text': area.allow_text,
                'allow_image': area.allow_image,
                'allow_clipart': area.allow_clipart,
                'max_elements': area.max_elements,
                'extra_price': area.extra_price,
            })
        return {
            'product_tmpl_id': self.id,
            'currency': self.currency_id.symbol,
            'base_price': self.customization_base_price,
            'text_price': self.customization_text_price,
            'image_price': self.customization_image_price,
            'areas': areas,
            'fonts': [{
                'id': f.id, 'name': f.name, 'family': f.css_family,
                'google': f.google_font,
            } for f in self.customization_font_ids],
            'colors': [{
                'id': c.id, 'name': c.name, 'color': c.html_color,
            } for c in self.customization_color_ids],
            'cliparts': [{
                'id': cp.id, 'name': cp.name, 'category': cp.category_id.name or '',
                'url': '%s/web/image/product.customization.clipart/%s/image' % (
                    base_url, cp.id),
                'extra_price': cp.extra_price,
            } for cp in self.customization_clipart_ids],
        }
