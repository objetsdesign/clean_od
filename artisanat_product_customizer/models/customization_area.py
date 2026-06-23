# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductCustomizationArea(models.Model):
    """Zone personnalisable d'un produit (ex: Devant, Dos, Manche...).

    Chaque zone définit une surface de travail (en % de l'image de base) sur
    laquelle le client pourra déposer du texte, des images ou des cliparts.
    """
    _name = 'product.customization.area'
    _description = "Zone de personnalisation produit"
    _order = 'sequence, id'

    name = fields.Char(string="Nom de la zone", required=True, translate=True)
    sequence = fields.Integer(string="Séquence", default=10)
    product_tmpl_id = fields.Many2one(
        'product.template', string="Produit", required=True, ondelete='cascade')

    # Image de fond optionnelle (sinon on prend l'image principale du produit)
    background_image = fields.Image(
        string="Image de fond de la zone",
        help="Visuel servant de base à cette zone (ex: photo du dos du produit). "
             "Si vide, l'image principale du produit est utilisée.")

    # Cadre de la zone exprimé en pourcentage de l'image (0 -> 100)
    pos_left = fields.Float(string="Position gauche (%)", default=15.0)
    pos_top = fields.Float(string="Position haut (%)", default=15.0)
    pos_width = fields.Float(string="Largeur (%)", default=70.0)
    pos_height = fields.Float(string="Hauteur (%)", default=70.0)

    # Types d'éléments autorisés sur cette zone
    allow_text = fields.Boolean(string="Autoriser le texte", default=True)
    allow_image = fields.Boolean(string="Autoriser l'image client", default=True)
    allow_clipart = fields.Boolean(string="Autoriser les cliparts", default=True)

    max_elements = fields.Integer(
        string="Nb max d'éléments", default=10,
        help="Nombre maximum d'objets que le client peut ajouter sur cette zone.")

    # Prix additionnel pour activer cette zone
    extra_price = fields.Float(string="Supplément de prix", default=0.0)

    color = fields.Integer(string="Couleur (kanban)")


class ProductCustomizationFont(models.Model):
    """Police de caractères proposée au client."""
    _name = 'product.customization.font'
    _description = "Police de personnalisation"
    _order = 'sequence, name'

    name = fields.Char(string="Nom affiché", required=True)
    sequence = fields.Integer(default=10)
    css_family = fields.Char(
        string="Famille CSS", required=True,
        help="Valeur 'font-family' utilisée par le configurateur (ex: 'Roboto').")
    google_font = fields.Boolean(
        string="Google Font", default=True,
        help="Charge la police depuis Google Fonts côté site web.")
    active = fields.Boolean(default=True)


class ProductCustomizationColor(models.Model):
    """Couleur proposée pour le texte ou les cliparts."""
    _name = 'product.customization.color'
    _description = "Couleur de personnalisation"
    _order = 'sequence, name'

    name = fields.Char(string="Nom", required=True, translate=True)
    sequence = fields.Integer(default=10)
    html_color = fields.Char(string="Code HTML", required=True, default="#000000")
    active = fields.Boolean(default=True)


class ProductCustomizationClipart(models.Model):
    """Bibliothèque de cliparts (motifs) réutilisables."""
    _name = 'product.customization.clipart'
    _description = "Clipart de personnalisation"
    _order = 'sequence, name'

    name = fields.Char(string="Nom", required=True, translate=True)
    sequence = fields.Integer(default=10)
    image = fields.Image(string="Image", required=True)
    category_id = fields.Many2one(
        'product.customization.clipart.category', string="Catégorie")
    extra_price = fields.Float(string="Supplément de prix", default=0.0)
    active = fields.Boolean(default=True)


class ProductCustomizationClipartCategory(models.Model):
    _name = 'product.customization.clipart.category'
    _description = "Catégorie de cliparts"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    clipart_ids = fields.One2many(
        'product.customization.clipart', 'category_id', string="Cliparts")
