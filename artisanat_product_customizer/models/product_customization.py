# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models


class ProductCustomization(models.Model):
    """Design personnalisé réalisé par un client.

    Stocke à la fois la définition technique (JSON Fabric.js, rejouable/éditable)
    et le rendu (PNG haute résolution) pour la production / l'impression.
    """
    _name = 'product.customization'
    _description = "Personnalisation produit du client"
    _order = 'create_date desc'

    name = fields.Char(string="Référence", default="Nouveau", copy=False)
    product_tmpl_id = fields.Many2one(
        'product.template', string="Produit", required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Variante")

    # Définition vectorielle (état complet du canvas, ré-éditable)
    design_json = fields.Text(string="Définition du design (JSON)")

    # Rendus
    preview_image = fields.Image(
        string="Aperçu", help="Aperçu basse résolution pour l'affichage panier.")
    print_image = fields.Image(
        string="Fichier d'impression",
        help="Rendu haute résolution destiné à la production.")

    # Récapitulatif lisible (textes saisis, polices, couleurs...)
    summary = fields.Text(string="Récapitulatif")

    extra_price = fields.Float(string="Supplément personnalisation", default=0.0)

    sale_line_ids = fields.One2many(
        'sale.order.line', 'customization_id', string="Lignes de commande")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'product.customization') or 'PERSO-NEW'
        return super().create(vals_list)

    def get_summary_dict(self):
        self.ensure_one()
        try:
            return json.loads(self.summary or '{}')
        except (ValueError, TypeError):
            return {}
