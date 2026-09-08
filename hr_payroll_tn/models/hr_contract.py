# -*- coding: utf-8 -*-
from odoo import fields, models


class HrContract(models.Model):
    _inherit = 'hr.contract'

    mode_traitement = fields.Selection([
        ('mensuel', 'Mensuel'),
        ('journalier', 'Journalier'),
        ('horaire', 'Horaire'),
    ], string="Mode de traitement", default='mensuel', required=True,
        help="Base de calcul du salaire : forfait mensuel, taux journalier "
             "ou taux horaire (utile pour le pointage machine/manuel).")

    taux_horaire = fields.Monetary(string="Taux horaire")
    taux_journalier = fields.Monetary(string="Taux journalier")
    nombre_heures_mensuelles = fields.Float(
        string="Heures mensuelles théoriques", default=173.33)
    nombre_jours_mensuels = fields.Float(
        string="Jours mensuels théoriques", default=26.0)

    soumis_cnss = fields.Boolean(string="Soumis à la CNSS", default=True)
    exonere_irpp = fields.Boolean(string="Exonéré d'IRPP", default=False)
