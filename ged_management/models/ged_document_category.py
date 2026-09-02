# -*- coding: utf-8 -*-
from odoo import fields, models


class GedDocumentCategory(models.Model):
    _name = 'ged.document.category'
    _description = "Catégorie de document GED"
    _order = 'name'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(string="Code")
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    color = fields.Integer(string="Couleur")

    _sql_constraints = [
        ('name_uniq', 'unique(name)', "Cette catégorie existe déjà."),
    ]
