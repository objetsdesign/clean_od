# -*- coding: utf-8 -*-
import base64
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ProductCustomizerController(http.Controller):

    @http.route('/shop/customizer/config', type='json', auth='public', website=True)
    def customizer_config(self, product_tmpl_id, **kw):
        """Renvoie la configuration du configurateur pour un produit."""
        tmpl = request.env['product.template'].sudo().browse(int(product_tmpl_id))
        if not tmpl.exists() or not tmpl.is_customizable:
            return {'error': 'not_customizable'}
        return tmpl.get_customizer_config()

    @http.route('/shop/customizer/save', type='json', auth='public', website=True)
    def customizer_save(self, product_tmpl_id, design_json=None, preview=None,
                        print_image=None, summary=None, extra_price=0.0,
                        product_id=None, **kw):
        """Crée (ou met à jour) un enregistrement de personnalisation et
        retourne son id, à transmettre ensuite à l'ajout panier."""
        tmpl = request.env['product.template'].sudo().browse(int(product_tmpl_id))
        if not tmpl.exists() or not tmpl.is_customizable:
            return {'error': 'not_customizable'}

        def _b64(data_url):
            if not data_url:
                return False
            if ',' in data_url:
                data_url = data_url.split(',', 1)[1]
            return data_url

        vals = {
            'product_tmpl_id': tmpl.id,
            'product_id': int(product_id) if product_id else False,
            'design_json': design_json or '',
            'preview_image': _b64(preview),
            'print_image': _b64(print_image),
            'summary': json.dumps(summary or {}, ensure_ascii=False),
            'extra_price': float(extra_price or 0.0),
        }
        customization = request.env['product.customization'].sudo().create(vals)
        return {'customization_id': customization.id, 'name': customization.name}

    @http.route('/shop/customizer/add', type='json', auth='public', website=True)
    def customizer_add_to_cart(self, product_id, customization_id, add_qty=1, **kw):
        """Ajoute la variante personnalisée au panier en liant la perso à la ligne."""
        order = request.website.sale_get_order(force_create=True)
        customization = request.env['product.customization'].sudo().browse(
            int(customization_id))
        if not customization.exists():
            return {'error': 'no_customization'}

        # On force une nouvelle ligne dédiée (chaque perso est unique)
        values = order._cart_update(
            product_id=int(product_id),
            add_qty=float(add_qty),
        )
        line = order.order_line.filtered(
            lambda l: l.product_id.id == int(product_id)
            and not l.customization_id)[:1]
        if line:
            line.sudo().write({'customization_id': customization.id})
            customization.sudo().product_id = line.product_id.id
            # La perso vient d'être liée APRÈS le calcul initial du prix :
            # on force le recalcul pour que le supplément entre dans le total.
            try:
                line.sudo()._compute_price_unit()
            except Exception:  # noqa: BLE001
                # Repli : on ajoute explicitement le supplément au prix unitaire.
                line.sudo().write({
                    'price_unit': (line.price_unit or 0.0)
                    + (customization.extra_price or 0.0),
                })

        return {
            'line_id': line.id if line else False,
            'cart_quantity': order.cart_quantity,
            'extra_price': customization.extra_price,
        }
