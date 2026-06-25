# -*- coding: utf-8 -*-
import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .glb_builder import build_glb

_logger = logging.getLogger(__name__)


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

    # --- 3D AUTOMATIQUE depuis une image (sans .glb ni convertisseur externe) ---
    auto_3d_from_image = fields.Boolean(
        string="Générer la 3D depuis une image", default=False,
        help="Active la génération locale d'un fichier .glb à partir d'une "
             "image, sans fichier .glb préexistant ni site de conversion externe.")
    model_3d_source_image = fields.Image(
        string="Image à convertir en 3D",
        help="Parcourez l'image à transformer en .glb. Si vide, l'image "
             "principale du produit est utilisée.")
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

    # ------------------------------------------------------------------
    #  3D AUTOMATIQUE : génération d'un .glb depuis l'image (Python pur,
    #  aucune dépendance, aucun site externe).
    # ------------------------------------------------------------------
    def _do_generate_glb(self):
        """Fabrique le .glb (image projetée sur la forme choisie) et le stocke
        dans `model_3d`. Sûr : ignore silencieusement les produits sans image."""
        for tmpl in self:
            img = tmpl.model_3d_source_image or tmpl.image_1024 or tmpl.image_1920
            if not img:
                continue
            try:
                raw = base64.b64decode(img)
                glb = build_glb(raw)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Échec génération .glb auto pour le produit %s", tmpl.id)
                continue
            fname = (tmpl.name or 'produit').strip().replace(' ', '_')[:40]
            tmpl.with_context(skip_auto_glb=True).write({
                'model_3d': base64.b64encode(glb),
                'model_3d_filename': "%s_auto.glb" % (fname or 'produit'),
            })

    def action_generate_glb_from_image(self):
        """Bouton : convertit l'image chargée (ou l'image produit) en .glb."""
        self.ensure_one()
        if not (self.model_3d_source_image or self.image_1024 or self.image_1920):
            raise UserError(_("Parcourez d'abord une image à convertir "
                              "(ou ajoutez une image au produit)."))
        self._do_generate_glb()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Modèle 3D généré"),
                'message': _("Le fichier .glb a été créé à partir de votre "
                             "image, sans service externe."),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        to_gen = records.filtered(
            lambda t: t.auto_3d_from_image and not t.model_3d
            and (t.model_3d_source_image or t.image_1024 or t.image_1920))
        if to_gen:
            to_gen._do_generate_glb()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_auto_glb'):
            triggers = {'auto_3d_from_image',
                        'model_3d_source_image', 'image_1920', 'image_1024'}
            if triggers & set(vals.keys()):
                targets = self.filtered(
                    lambda t: t.auto_3d_from_image
                    and (t.model_3d_source_image or t.image_1024 or t.image_1920))
                if targets:
                    targets._do_generate_glb()
        return res

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
                'image_url': (
                    '/web/image/product.template/%s/model_3d_source_image' % self.id
                    if self.model_3d_source_image
                    else '/web/image/product.template/%s/image_1024' % self.id
                ),
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
