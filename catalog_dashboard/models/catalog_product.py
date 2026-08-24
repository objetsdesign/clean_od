# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


DEV_STAGES = [
    ('idee', "1. Idée"),
    ('design', "2. Design en cours"),
    ('sourcing', "3. Sourcing"),
    ('prototype_v0', "4. Prototype V0"),
    ('prototype_valide', "5. Prototype validé"),
    ('bat_valide', "6. BAT validé"),
    ('pre_serie', "7. Pré-série"),
    ('production_planifiee', "8. Production planifiée"),
    ('production_en_cours', "9. Production en cours"),
    ('produit_disponible', "10. Produit disponible"),
    ('produit_archive', "11. Produit archivé"),
]
DEV_STAGE_DONE = ('produit_disponible', 'produit_archive')
DEV_STAGE_TO_VALIDATE = ('prototype_v0', 'bat_valide')  # prototypes/BAT en attente de validation


class CatalogProduct(models.Model):
    _name = 'catalog.product'
    _description = "Référence produit du catalogue (variante / SKU)"
    _order = 'model_id, sku'
    _rec_name = 'sku'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ---------- Hiérarchie ----------
    model_id = fields.Many2one(
        'catalog.model', string="Modèle", required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    collection_id = fields.Many2one(related='model_id.collection_id', string="Collection", store=True, readonly=True)
    brand_id = fields.Many2one(related='model_id.collection_id.brand_id', string="Marque", store=True, readonly=True)
    axe_id = fields.Many2one(related='model_id.collection_id.brand_id.axe_id', string="Axe", store=True, readonly=True)
    accent_color = fields.Char(related='model_id.collection_id.accent_color', string="Couleur collection", store=False)

    # ---------- Identification ----------
    sku = fields.Char(string="SKU", tracking=True)
    ref_nom = fields.Char(string="Réf. nom")
    brand_label = fields.Char(
        string="Étiquette / mention (texte libre)",
        help="Texte libre historique (ex. mention d'étiquette ou de fournisseur). "
             "Ce n'est PAS la Marque structurée : utilisez le champ Marque (hérité du Modèle > Collection) pour cela.",
    )
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

    # ---------- Cycle de développement (11 étapes) ----------
    dev_stage = fields.Selection(
        DEV_STAGES, string="Statut de développement", default='idee',
        tracking=True, group_expand='_expand_dev_stages',
        help="Étape du cycle de développement produit, de l'idée au produit archivé. "
             "Indépendant du statut du stock.",
    )
    dev_stage_category = fields.Selection(
        [
            ('developpement', "En développement"),
            ('production', "En production"),
            ('disponible', "Disponible"),
            ('archive', "Archivé"),
        ],
        string="Catégorie d'étape", compute='_compute_dev_stage_category', store=True,
    )
    date_echeance = fields.Date(
        string="Échéance de l'étape en cours", tracking=True,
        help="Date prévue pour terminer l'étape actuelle du cycle de développement.",
    )
    is_late = fields.Boolean(string="En retard", compute='_compute_is_late', store=True)
    to_validate = fields.Boolean(
        string="À valider (prototype / BAT)", compute='_compute_to_validate', store=True,
        help="Vrai si la référence est en attente de validation d'un prototype ou d'un BAT.",
    )

    # ---------- Coût (cible / réel), distinct du prix ----------
    cout_cible = fields.Float(string="Coût cible", digits=(12, 3))
    cout_production = fields.Float(
        string="Coût de production réel (interne)", digits=(12, 3),
        help="Coût de fabrication interne réel de la référence. "
             "Ne correspond ni au prix de revient (coût de production + logistique/frais annexes) "
             "ni au prix de vente public. À ne pas confondre avec ces deux notions.",
    )
    cout_valide = fields.Boolean(string="Coût validé", tracking=True)
    ecart_cout = fields.Float(
        string="Écart coût cible / réel", compute='_compute_ecart_cout', store=True, digits=(12, 3),
        help="Coût de production réel moins coût cible. Positif = dépassement du coût cible.",
    )

    # ---------- Fiche technique ----------
    fiche_technique_complete = fields.Boolean(
        string="Fiche technique complète", compute='_compute_fiche_technique_complete', store=True,
        help="Vrai si dimensions, matière principale, couleur principale, photo et coût de production sont renseignés.",
    )

    # ---------- Stock ----------
    stock = fields.Integer(string="Stock disponible", tracking=True)
    stock_reserve = fields.Integer(string="Stock réservé")
    stock_previsionnel = fields.Integer(
        string="Stock prévisionnel", help="Entrées de stock attendues (production en cours, commandes fournisseur...).",
    )
    stock_alert_threshold = fields.Integer(string="Seuil d'alerte stock", default=5)
    low_stock = fields.Boolean(string="Stock faible", compute='_compute_low_stock', store=True)
    stock_status = fields.Selection(
        [
            ('rupture', "Rupture de stock"),
            ('faible', "Stock faible"),
            ('disponible', "Disponible"),
        ],
        string="Statut du stock",
        compute='_compute_stock_status', store=True, tracking=True,
        help="État du stock disponible pour cette référence, indépendant du statut de développement/production.",
    )

    # ---------- Mise en marché ----------
    shopify_status = fields.Selection(
        [
            ('non_pret', "Non prêt"),
            ('pret', "Prêt à publier"),
            ('publie', "Publié"),
        ],
        string="Statut Shopify / marketplaces", default='non_pret', tracking=True,
    )
    doc_conformite_ok = fields.Boolean(
        string="Documents de conformité complets", tracking=True,
        help="À cocher lorsque tous les documents de conformité requis (ex. REACH, étiquetage...) sont disponibles.",
    )

    # ---------- Historique production (hérité, avant refonte) ----------
    prod_1 = fields.Integer(string="Prod 1 (legacy)")
    date_livrable_1 = fields.Char(string="Date livrable 1 (legacy, texte libre)")
    prod_2 = fields.Integer(string="Prod 2 (legacy)")
    date_livrable_2 = fields.Char(string="Date livrable 2 (legacy, texte libre)")

    active = fields.Boolean(default=True)

    def _expand_dev_stages(self, stages, domain):
        return [key for key, _label in DEV_STAGES]

    @api.depends('dev_stage')
    def _compute_dev_stage_category(self):
        for rec in self:
            if rec.dev_stage == 'produit_disponible':
                rec.dev_stage_category = 'disponible'
            elif rec.dev_stage == 'produit_archive':
                rec.dev_stage_category = 'archive'
            elif rec.dev_stage in ('production_planifiee', 'production_en_cours'):
                rec.dev_stage_category = 'production'
            else:
                rec.dev_stage_category = 'developpement'

    @api.depends('date_echeance', 'dev_stage')
    def _compute_is_late(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_late = bool(
                rec.date_echeance and rec.date_echeance < today and rec.dev_stage not in DEV_STAGE_DONE
            )

    @api.depends('dev_stage')
    def _compute_to_validate(self):
        for rec in self:
            rec.to_validate = rec.dev_stage in DEV_STAGE_TO_VALIDATE

    @api.depends('cout_production', 'cout_cible')
    def _compute_ecart_cout(self):
        for rec in self:
            rec.ecart_cout = (rec.cout_production or 0.0) - rec.cout_cible if rec.cout_cible else 0.0

    @api.depends('dimensions', 'matiere_principale', 'couleur_principale', 'image_1920', 'cout_production')
    def _compute_fiche_technique_complete(self):
        for rec in self:
            rec.fiche_technique_complete = bool(
                rec.dimensions and rec.matiere_principale and rec.couleur_principale
                and rec.image_1920 and rec.cout_production
            )

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
