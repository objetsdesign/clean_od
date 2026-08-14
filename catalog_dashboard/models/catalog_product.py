# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CatalogProduct(models.Model):
    _name = 'catalog.product'
    _description = "Référence produit du catalogue"
    _order = 'collection_id, sku'
    _rec_name = 'sku'

    # ---------- Identification ----------
    collection_id = fields.Many2one(
        'catalog.collection', string="Collection", required=True,
        ondelete='cascade', index=True,
    )
    accent_color = fields.Char(related='collection_id.accent_color', string="Couleur collection", store=False)
    sku = fields.Char(string="SKU")
    ref_nom = fields.Char(string="Réf. nom")
    brand_label = fields.Char(string="Marque / étiquette")
    description = fields.Text(string="Description")
    dimensions = fields.Char(string="Dimensions")
    image_1920 = fields.Image(string="Photo", max_width=1920, max_height=1920)

    # ---------- Matières & couleurs ----------
    matiere_principale = fields.Char(string="Matière principale")
    couleur_principale = fields.Char(string="Couleur principale")
    matiere_secondaire = fields.Char(string="Matière secondaire")
    couleur_secondaire = fields.Char(string="Couleur secondaire")
    doublure = fields.Char(string="Doublure")
    couleur_doublure = fields.Char(string="Couleur doublure")
    motif = fields.Char(string="Motif")

    # ---------- Accessoires ----------
    accessoire_1 = fields.Char(string="Accessoire 1")
    accessoire_2 = fields.Char(string="Accessoire 2")
    accessoire_3 = fields.Char(string="Accessoire 3")
    accessoire_4 = fields.Char(string="Accessoire 4")
    accessoire_5 = fields.Char(string="Accessoire 5")
    accessoire_6 = fields.Char(string="Accessoire 6")
    accessoires_cuir = fields.Char(string="Accessoires cuir")
    packaging_individuel = fields.Char(string="Packaging individuel")

    # ---------- Production / stock / coût ----------
    prod_1 = fields.Integer(string="Prod 1")
    date_livrable_1 = fields.Char(string="Date livrable 1")
    prod_2 = fields.Integer(string="Prod 2")
    date_livrable_2 = fields.Char(string="Date livrable 2")
    stock = fields.Integer(string="Stock")
    cout_production = fields.Float(string="Coût de production", digits=(12, 3))

    status = fields.Selection(
        [
            ('realise', "Réalisé"),
            ('en_cours', "En cours"),
            ('lancement2', "2ème lancement"),
            ('a_planifier', "À planifier"),
        ],
        string="Statut de production",
        compute='_compute_status', store=True,
    )

    active = fields.Boolean(default=True)

    @api.depends('date_livrable_1', 'date_livrable_2')
    def _compute_status(self):
        for rec in self:
            text = (rec.date_livrable_1 or rec.date_livrable_2 or '').strip().lower()
            if 'réalisé' in text or 'realise' in text:
                rec.status = 'realise'
            elif 'en cours' in text:
                rec.status = 'en_cours'
            elif 'lancement' in text:
                rec.status = 'lancement2'
            else:
                rec.status = 'a_planifier'

    def _compute_display_name(self):
        for rec in self:
            label = rec.sku or rec.ref_nom or _("Nouvelle référence")
            if rec.ref_nom and rec.sku and rec.ref_nom != rec.sku:
                label = f"[{rec.sku}] {rec.ref_nom}"
            rec.display_name = label
