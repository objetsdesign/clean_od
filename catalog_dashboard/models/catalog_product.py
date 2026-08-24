# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CatalogProduct(models.Model):
    _name = 'catalog.product'
    _description = "Référence produit du catalogue"
    _order = 'collection_id, sku'
    _rec_name = 'sku'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ---------- Identification ----------
    collection_id = fields.Many2one(
        'catalog.collection', string="Collection", required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    accent_color = fields.Char(related='collection_id.accent_color', string="Couleur collection", store=False)
    sku = fields.Char(string="SKU", tracking=True)
    ref_nom = fields.Char(string="Réf. nom")
    brand_label = fields.Char(string="Marque / étiquette")
    description = fields.Text(string="Description")
    dimensions = fields.Char(string="Dimensions")
    image_1920 = fields.Image(string="Photo", max_width=1920, max_height=1920)

    favorite = fields.Boolean(string="Coup de cœur")
    image_ids = fields.One2many(
        'catalog.product.image', 'product_id', string="Galerie photo"
    )
    image_count = fields.Integer(string="Nb. photos", compute='_compute_image_count')

    # ---------- Matières & couleurs ----------
    matiere_principale = fields.Char(string="Matière principale")
    couleur_principale = fields.Char(string="Couleur principale")
    couleur_principale_hex = fields.Char(string="Pastille couleur principale", default='#C9BBA0')
    matiere_secondaire = fields.Char(string="Matière secondaire")
    couleur_secondaire = fields.Char(string="Couleur secondaire")
    couleur_secondaire_hex = fields.Char(string="Pastille couleur secondaire", default='#8C5A34')
    doublure = fields.Char(string="Doublure")
    couleur_doublure = fields.Char(string="Couleur doublure")
    couleur_doublure_hex = fields.Char(string="Pastille couleur doublure", default='#3F3A32')
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
    stock = fields.Integer(string="Stock", tracking=True)
    stock_alert_threshold = fields.Integer(string="Seuil d'alerte stock", default=5)
    low_stock = fields.Boolean(string="Stock faible", compute='_compute_low_stock', store=True)
    cout_production = fields.Float(
        string="Coût de production (interne)", digits=(12, 3),
        help="Coût de fabrication interne de la référence. "
             "Ne correspond ni au prix de revient (coût de production + logistique/frais annexes) "
             "ni au prix de vente public. À ne pas confondre avec ces deux notions.",
    )

    # NOTE : ce champ est un statut de PRODUCTION (avancement de fabrication).
    # Il ne renseigne pas sur la disponibilité en stock : voir le champ `stock_status`
    # pour l'état du stock (rupture / faible / disponible).
    status = fields.Selection(
        [
            ('realise', "Production réalisée"),
            ('en_cours', "Production en cours"),
            ('lancement2', "2ème lancement en production"),
            ('a_planifier', "Production à planifier"),
        ],
        string="Statut de production",
        compute='_compute_status', store=True, tracking=True,
        help="Avancement de la fabrication de la référence. Indépendant du niveau de stock actuel.",
    )

    stock_status = fields.Selection(
        [
            ('rupture', "Rupture de stock"),
            ('faible', "Stock faible"),
            ('disponible', "Disponible"),
        ],
        string="Statut du stock",
        compute='_compute_stock_status', store=True, tracking=True,
        help="État du stock disponible pour cette référence, indépendant du statut de production.",
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

    @api.depends('stock', 'stock_alert_threshold')
    def _compute_low_stock(self):
        for rec in self:
            rec.low_stock = rec.stock <= rec.stock_alert_threshold

    @api.depends('stock', 'stock_alert_threshold')
    def _compute_stock_status(self):
        for rec in self:
            if rec.stock <= 0:
                rec.stock_status = 'rupture'
            elif rec.stock <= rec.stock_alert_threshold:
                rec.stock_status = 'faible'
            else:
                rec.stock_status = 'disponible'

    @api.depends('image_ids')
    def _compute_image_count(self):
        for rec in self:
            rec.image_count = len(rec.image_ids)

    def _compute_display_name(self):
        for rec in self:
            label = rec.sku or rec.ref_nom or _("Nouvelle référence")
            if rec.ref_nom and rec.sku and rec.ref_nom != rec.sku:
                label = f"[{rec.sku}] {rec.ref_nom}"
            rec.display_name = label

    def action_toggle_favorite(self):
        for rec in self:
            rec.favorite = not rec.favorite

    def action_print_fiche_technique(self):
        return self.env.ref('catalog_dashboard.action_report_catalog_product').report_action(self)


class CatalogProductImage(models.Model):
    _name = 'catalog.product.image'
    _description = "Photo de la galerie produit"
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Libellé")
    image_1920 = fields.Image(string="Photo", max_width=1920, max_height=1920, required=True)
    product_id = fields.Many2one('catalog.product', string="Référence produit", ondelete='cascade', required=True)
