# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductCustomizationPocket(models.Model):
    """Poche ajoutable au produit (poche plaquée, zippée, à rabat...).

    Chaque poche est un VISUEL (image PNG, idéalement à fond transparent) qui
    se superpose au produit à un EMPLACEMENT DÉJÀ PRÉCISÉ (coordonnées en % du
    visuel). Côté configurateur, les poches sont MUTUELLEMENT EXCLUSIVES :
    appliquer une poche retire automatiquement la précédente.
    """
    _name = 'product.customization.pocket'
    _description = "Poche produit"
    _order = 'sequence, id'

    name = fields.Char(string="Nom de la poche", required=True, translate=True)
    sequence = fields.Integer(default=10)
    product_tmpl_id = fields.Many2one(
        'product.template', string="Produit", required=True, ondelete='cascade')

    description = fields.Char(string="Description", translate=True)
    image = fields.Image(
        string="Visuel de la poche (PNG transparent)",
        help="Image superposée au produit. Privilégiez un PNG à fond "
             "transparent pour un rendu propre sur n'importe quelle matière.")

    # --- Emplacement DÉJÀ PRÉCISÉ (centre de la poche, en % du visuel) ---
    pos_left = fields.Float(
        string="Position X (%)", default=50.0,
        help="Position horizontale du CENTRE de la poche, en % de la largeur.")
    pos_top = fields.Float(
        string="Position Y (%)", default=62.0,
        help="Position verticale du CENTRE de la poche, en % de la hauteur.")
    pos_width = fields.Float(
        string="Largeur (%)", default=32.0,
        help="Largeur de la poche, en % de la largeur du visuel.")

    extra_price = fields.Float(string="Supplément de prix", default=0.0)
    active = fields.Boolean(default=True)
