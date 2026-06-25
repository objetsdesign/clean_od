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

    # --- Matières proposées (cuir, daim, toile...) ---
    customization_material_ids = fields.Many2many(
        'product.customization.material', string="Matières proposées")
    # --- Bibliothèque de textures proposées (prêtes à l'emploi) ---
    customization_texture_ids = fields.Many2many(
        'product.customization.texture', string="Textures proposées")
    allow_diy_texture = fields.Boolean(
        string="Autoriser sa propre texture (DIY)", default=True,
        help="Le client peut téléverser sa propre image de texture pour "
             "recouvrir tout le produit.")

    # --- Dimensions proposées ---
    customization_dimension_ids = fields.Many2many(
        'product.customization.dimension', string="Dimensions proposées")

    customization_base_price = fields.Float(
        string="Frais de personnalisation",
        help="Supplément forfaitaire ajouté dès qu'une personnalisation est créée.")

    # --- Coloris produit (swap d'image 2D + couleur matière 3D) ---
    colorway_ids = fields.One2many(
        'product.customization.colorway', 'product_tmpl_id',
        string="Coloris du produit")

    # --- Modèle 3D ---
    model_3d = fields.Binary(
        string="Modèle 3D (.glb)", attachment=True,
        help="Fichier glTF binaire (.glb) du produit. Active la vue 3D.")
    model_3d_filename = fields.Char(string="Nom du fichier 3D")

    # --- 3D AUTOMATIQUE depuis l'image (sans .glb ni convertisseur externe) ---
    auto_3d_from_image = fields.Boolean(
        string="3D auto depuis l'image", default=False,
        help="Génère une vue 3D directement à partir de l'image du produit, "
             "sans fichier .glb ni site de conversion externe. La photo est "
             "appliquée sur une forme 3D paramétrable et reste personnalisable.")
    model_3d_shape = fields.Selection(
        selection=[
            ('plane', "Plan plat (poster, sticker, tableau)"),
            ('card', "Carte légèrement incurvée"),
            ('box', "Boîte / coffret"),
            ('cylinder', "Cylindre (mug, tasse, bougie)"),
            ('pillow', "Coussin / pochette"),
        ],
        string="Forme 3D auto", default='card',
        help="Forme de base sur laquelle l'image du produit est projetée "
             "pour générer la 3D automatiquement.")
    model_3d_mesh = fields.Char(
        string="Mesh à personnaliser (3D)",
        help="Nom du mesh du modèle qui recevra le design (texte/image). "
             "Laisser vide pour appliquer la texture au premier mesh trouvé.")
    model_3d_camera_dist = fields.Float(
        string="Distance caméra 3D", default=3.0,
        help="Distance initiale de la caméra (ajustez selon la taille du modèle).")

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
            'colorways': [{
                'id': cw.id,
                'name': cw.name,
                'swatch': cw.swatch_color,
                'material_hex': cw.material_hex,
                'extra_price': cw.extra_price,
                'image_url': (
                    '/web/image/product.customization.colorway/%s/image' % cw.id
                    if cw.image else None),
            } for cw in self.colorway_ids],
            'model_3d': {
                'url': ('/web/content/product.template/%s/model_3d' % self.id
                        if self.model_3d else None),
                'mesh': self.model_3d_mesh or '',
                'camera_dist': self.model_3d_camera_dist or 3.0,
            },
            # 3D générée automatiquement depuis l'image (sans .glb externe)
            'auto_3d': {
                'enabled': self.auto_3d_from_image and not self.model_3d,
                'shape': self.model_3d_shape or 'card',
                'image_url': '/web/image/product.template/%s/image_1024' % self.id,
            },
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
            'allow_diy_texture': self.allow_diy_texture,
            'materials': [{
                'id': mt.id,
                'name': mt.name,
                'description': mt.description or '',
                'swatch': mt.swatch_color or mt.material_hex or '#ccc',
                'material_hex': mt.material_hex or '#8B5A2B',
                'extra_price': mt.extra_price,
                'tiled': mt.texture_tiled,
                'tex_scale': mt.texture_scale or 1.0,
                'texture_url': (
                    '/web/image/product.customization.material/%s/texture_image' % mt.id
                    if mt.texture_image else None),
            } for mt in self.customization_material_ids],
            'dimensions': [{
                'id': dim.id,
                'name': dim.name,
                'label': dim.display_name,
                'description': dim.description or '',
                'width': dim.width_cm,
                'height': dim.height_cm,
                'depth': dim.depth_cm,
                'extra_price': dim.extra_price,
            } for dim in self.customization_dimension_ids],
            'textures': [{
                'id': tx.id,
                'name': tx.name,
                'category': tx.category or '',
                'tiled': tx.tiled,
                'tex_scale': tx.texture_scale or 1.0,
                'extra_price': tx.extra_price,
                'url': '/web/image/product.customization.texture/%s/image' % tx.id,
            } for tx in self.customization_texture_ids],
        }
