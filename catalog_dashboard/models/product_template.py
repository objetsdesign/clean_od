# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ---------- Lien vers le catalogue ----------
    catalog_product_ids = fields.One2many(
        'catalog.product', 'product_tmpl_id', string="Références catalogue liées",
    )
    catalog_product_count = fields.Integer(
        string="Nb. références catalogue", compute='_compute_catalog_product_count',
    )
    in_catalog = fields.Boolean(
        string="Dans le catalogue", compute='_compute_catalog_product_count', store=True,
        help="Vrai si ce produit Odoo est rattaché à au moins une référence du catalogue "
             "(collection / modèle / variante).",
    )

    # ---------- Statut de stock (réel, basé sur l'inventaire Odoo) ----------
    catalog_stock_alert_threshold = fields.Integer(
        string="Seuil d'alerte stock", default=5,
        help="En dessous (ou égal à) de ce seuil de quantité disponible, le produit est "
             "considéré en stock faible. À zéro ou moins : rupture de stock.",
    )
    catalog_stock_status = fields.Selection(
        [
            ('rupture', "Rupture de stock"),
            ('faible', "Stock faible"),
            ('disponible', "Disponible"),
        ],
        string="Statut du stock (Odoo)",
        compute='_compute_catalog_stock_status', store=True,
        help="État du stock disponible réel (inventaire Odoo), calculé à partir de la "
             "quantité disponible (qty_available) et du seuil d'alerte.",
    )

    @api.depends('catalog_product_ids')
    def _compute_catalog_product_count(self):
        for rec in self:
            rec.catalog_product_count = len(rec.catalog_product_ids)
            rec.in_catalog = bool(rec.catalog_product_ids)

    @api.depends('qty_available', 'catalog_stock_alert_threshold', 'type')
    def _compute_catalog_stock_status(self):
        for rec in self:
            qty = rec.qty_available or 0.0
            if qty <= 0:
                rec.catalog_stock_status = 'rupture'
            elif qty <= rec.catalog_stock_alert_threshold:
                rec.catalog_stock_status = 'faible'
            else:
                rec.catalog_stock_status = 'disponible'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_catalog_auto_import'):
            records._auto_create_catalog_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'image_1920' in vals and not self.env.context.get('skip_catalog_auto_import'):
            self._sync_image_to_catalog_products()
        return res

    def _sync_image_to_catalog_products(self):
        """Propage immédiatement la photo du produit Odoo vers les références catalogue
        auto-importées liées qui n'ont pas encore de photo (ajout ou modification de la
        photo côté Odoo, après la création initiale de la référence)."""
        for rec in self:
            if not rec.image_1920:
                continue
            targets = rec.catalog_product_ids.filtered(lambda c: c.auto_imported and not c.image_1920)
            if targets:
                targets.write({'image_1920': rec.image_1920})

    @api.model
    def _register_hook(self):
        """Rattrape, à chaque (re)chargement du registre (installation, mise à niveau,
        redémarrage), tout produit Odoo existant qui n'a pas encore de référence catalogue
        liée — pour que le Tableau de bord Collections et les Références produit du catalogue
        couvrent bien tous les produits Odoo."""
        res = super()._register_hook()
        try:
            orphans = self.search([('catalog_product_ids', '=', False)])
            if orphans:
                orphans._auto_create_catalog_product()
            self.env['catalog.product']._backfill_missing_images_from_odoo()
        except Exception:
            _logger.exception(
                "catalog_dashboard: échec du rattrapage automatique des références "
                "catalogue pour les produits Odoo existants"
            )
        return res

    def _auto_create_catalog_product(self):
        """Crée automatiquement une référence catalogue (auto-importée, classée dans
        'Import Odoo > Non classé') pour chaque produit Odoo de ce recordset qui n'en a
        pas encore, afin qu'il soit visible dans le catalogue (dashboard Collections,
        Références produit) en plus de la fiche produit Odoo standard."""
        CatalogProduct = self.env['catalog.product']
        default_model = CatalogProduct._get_default_import_model()
        if not default_model:
            return
        vals_list = []
        for rec in self:
            if rec.catalog_product_ids:
                continue
            vals_list.append({
                'model_id': default_model.id,
                'product_tmpl_id': rec.id,
                'sku': rec.default_code or rec.name,
                'ref_nom': rec.name,
                'stock': int(rec.qty_available or 0),
                'image_1920': rec.image_1920,
                'auto_imported': True,
            })
        if vals_list:
            CatalogProduct.create(vals_list)

    def action_view_catalog_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Références catalogue liées",
            'res_model': 'catalog.product',
            'view_mode': 'list,kanban,form',
            'domain': [('product_tmpl_id', '=', self.id)],
        }

