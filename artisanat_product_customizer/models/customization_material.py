# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductCustomizationMaterial(models.Model):
    """Matière proposée au client (Cuir, Daim, Toile, Liège...).

    Sélectionner une matière dans le configurateur :
    - applique sa COULEUR matière (hex) au produit, et/ou
    - REMPLIT TOUT LE PRODUIT avec son image de TEXTURE (si fournie).

    La texture est appliquée comme fond plein du canvas Fabric, qui sert
    de carte (map) au mesh 3D : le produit entier est donc recouvert.
    """
    _name = 'product.customization.material'
    _description = "Matière de personnalisation"
    _order = 'sequence, name'

    name = fields.Char(string="Nom de la matière", required=True, translate=True)
    sequence = fields.Integer(default=10)

    swatch_color = fields.Char(
        string="Pastille (hex)", default="#8B5A2B",
        help="Couleur affichée sur la pastille de sélection (si pas de texture).")
    texture_image = fields.Image(
        string="Image de texture",
        help="Visuel de la matière (cuir, toile, bois...). S'il est fourni, "
             "il recouvre TOUT le produit. Préférez une image carrée et "
             "raccordable (tileable) pour un beau rendu.")
    material_hex = fields.Char(
        string="Couleur matière (hex)", default="#8B5A2B",
        help="Couleur appliquée si aucune image de texture n'est définie.")

    texture_tiled = fields.Boolean(
        string="Texture répétée (tileable)", default=True,
        help="Répète l'image en mosaïque sur tout le produit (recommandé pour "
             "cuir, toile, denim...). Décochez pour étirer l'image en plein cadre.")
    texture_scale = fields.Float(
        string="Échelle de la texture", default=1.0,
        help="Facteur de taille des motifs répétés (1 = taille native, "
             "0.5 = motifs deux fois plus petits).")

    description = fields.Char(string="Description", translate=True)
    extra_price = fields.Float(string="Supplément de prix", default=0.0)
    active = fields.Boolean(default=True)


class ProductCustomizationDimension(models.Model):
    """Dimension / taille proposée pour le produit.

    Ex : « Petit (20×15 cm) », « Moyen (30×22 cm) », « Grand (40×30 cm) ».
    """
    _name = 'product.customization.dimension'
    _description = "Dimension de personnalisation"
    _order = 'sequence, id'

    name = fields.Char(string="Nom / taille", required=True, translate=True)
    sequence = fields.Integer(default=10)

    width_cm = fields.Float(string="Largeur (cm)")
    height_cm = fields.Float(string="Hauteur (cm)")
    depth_cm = fields.Float(string="Profondeur (cm)")

    description = fields.Char(string="Description", translate=True)
    extra_price = fields.Float(string="Supplément de prix", default=0.0)
    active = fields.Boolean(default=True)

    @api.depends('name', 'width_cm', 'height_cm', 'depth_cm')
    def _compute_display_name(self):
        for rec in self:
            dims = []
            if rec.width_cm:
                dims.append("%g" % rec.width_cm)
            if rec.height_cm:
                dims.append("%g" % rec.height_cm)
            if rec.depth_cm:
                dims.append("%g" % rec.depth_cm)
            rec.display_name = (
                "%s (%s cm)" % (rec.name, "×".join(dims)) if dims else (rec.name or "")
            )
