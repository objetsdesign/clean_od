import json

from odoo import fields, models, api, _
from odoo.exceptions import UserError


class SaleOrderInherit(models.Model):
    _inherit = "sale.order"

    @api.model
    def _get_lines_sudo(self):
        """Retourne toutes les lignes de commande avec sudo() pour éviter AccessError sur product.product"""
        return self.order_line.sudo()

    show_conditions_tab = fields.Boolean(
        string="Afficher Conditions", compute="_compute_show_conditions_tab",readonly=True
    )
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        domain="[]",
        context={'company_id': False},
    )

    @api.depends('partner_id', 'partner_id.category_id')
    def _compute_show_conditions_tab(self):
        for order in self:
            if order.partner_id:
                order.show_conditions_tab = any(cat.name == "B2B" for cat in order.partner_id.category_id)
            else:
                order.show_conditions_tab = False
    partner_ref_related = fields.Char(
        string="Référence partenaire",
        related="partner_id.partner_ref",
        store=True,
        readonly=True
    )
    def action_quotation_send(self):
        """Override pour utiliser un template d'e-mail personnalisé."""
        self.filtered(lambda so: so.state in ('draft', 'sent')).order_line._validate_analytic_distribution()
        lang = self.env.context.get('lang')

        ctx = {
            'default_model': 'sale.order',
            'default_res_ids': self.ids,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_layout_with_responsible_signature',
            'proforma': self.env.context.get('proforma', False),
        }

        if len(self) > 1:
            ctx['default_composition_mode'] = 'mass_mail'
        else:
            ctx.update({
                'force_email': True,
                'model_description': self.with_context(lang=lang).type_name,
            })

            custom_template = self.env.ref('objetdesign_report_template.email_template_custom_devis02',
                                           raise_if_not_found=False)
            if custom_template:
                ctx.update({
                    'default_template_id': custom_template.id,
                    'mark_so_as_sent': True,
                })
                if custom_template.lang:
                    lang = custom_template._render_lang(self.ids)[self.id]
            else:
                mail_template = self._find_mail_template()
                if mail_template:
                    ctx.update({
                        'default_template_id': mail_template.id,
                        'mark_so_as_sent': True,
                    })
                    if mail_template.lang:
                        lang = mail_template._render_lang(self.ids)[self.id]
                else:
                    for order in self:
                        order._portal_ensure_token()

        action = {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(False, 'form')],
            'target': 'new',
            'context': ctx,
        }

        if (
                self.env.context.get('check_document_layout')
                and not self.env.context.get('discard_logo_check')
                and self.env.is_admin()
                and not self.env.company.external_report_layout_id
        ):
            layout_action = self.env['ir.actions.report']._action_configure_external_report_layout(action)
            action.pop('close_on_report_download', None)
            layout_action['context']['dialog_size'] = 'extra-large'
            return layout_action

        return action


    def action_update_prices(self):
        self.ensure_one()

        if not self.pricelist_id:
            raise UserError("Veuillez sélectionner une liste de prix.")

        rates = {
            "EUR": 1.0,
            "USD": 1.157100,
            "CNY": 8.237700,
            "CNH": 8.210959,
            "TND": 3.4015637,
        }

        for line in self.order_line:
            if not line.base_price_eur:
                line.base_price_eur = line.price_unit  # Premier enregistrement

            base = line.base_price_eur
            rate = rates.get(self.currency_id.name, 1.0)

            line.price_unit = base * rate

    def action_confirm(self):
        """Override pour créer une commande fournisseur au lieu de confirmer la vente."""
        res = super(SaleOrderInherit, self).action_confirm()

        PurchaseOrder = self.env['purchase.order']

        for order in self:
            if not order.order_line:
                raise UserError("Aucune ligne de produit à convertir en commande fournisseur.")

            po_currency = order.currency_id or (
                order.pricelist_id.currency_id if order.pricelist_id else self.env.user.company_id.currency_id)

            purchase_order = (PurchaseOrder
            .create({
                'partner_id': order.partner_id.id,
                'origin': order.name,
                'sale_order_id': order.id,  # lien si tu as un champ custom sur purchase.order
                'currency_id': po_currency.id,  # même devise
                'pricelist_id': order.pricelist_id.id if order.pricelist_id else False,
                'order_line': [
                    (0, 0, {
                        'product_id': line.product_id.id,
                        'name': line.name,
                        'product_qty': line.product_uom_qty,
                        'product_uom': line.product_uom.id,
                        'price_unit': line.price_unit,  # optionnel : convertir selon currency
                        'date_planned': fields.Date.today(),
                    }) for line in order.order_line
                ],
            }))

            order.state = 'sale'


            order.message_post(body=_(
                "Commande fournisseur <a href=# data-oe-model='purchase.order' data-oe-id='%s'>%s</a> créée avec succès."
            ) % (purchase_order.id, purchase_order.name))

        return res

    tech_doc = fields.Text(
        string="Technical Document",
        compute="_compute_multilang_fields",
        store=True
    )
    delivery_info = fields.Text(
        string="Delivery",
        compute="_compute_multilang_fields",
        store=True
    )
    payment_info = fields.Text(
        string="Payment",
        compute="_compute_multilang_fields",
        store=True
    )
    validity_info = fields.Text(
        string="Validity",
        compute="_compute_multilang_fields",
        store=True
    )
    delay_info = fields.Text(
        string="Lead Time",
        compute="_compute_multilang_fields",
        store=True
    )
    inspection_info = fields.Text(
        string="Inspections",
        compute="_compute_multilang_fields",
        store=True
    )
    address_china = fields.Char(
        string="China Address",
        compute="_compute_multilang_fields",
        store=True
    )
    address_tunisia = fields.Char(
        string="Tunisia Address",
        compute="_compute_multilang_fields",
        store=True
    )
    consigne = fields.Text(
        string="Consigne",
        compute="_compute_multilang_fields",
        store=True
    )
    delivery_addr=fields.Text(string=" Delivery Address",
        compute="_compute_multilang_fields",
        store=True)
    @api.depends()
    def _compute_multilang_fields(self):
        lang = self.env.lang  # langue active
        for rec in self:
            rec.tech_doc = self._get_multilang_value('tech_doc', lang)
            rec.delivery_info = self._get_multilang_value('delivery_info', lang)
            rec.payment_info = self._get_multilang_value('payment_info', lang)
            rec.validity_info = self._get_multilang_value('validity_info', lang)
            rec.delay_info = self._get_multilang_value('delay_info', lang)
            rec.inspection_info = self._get_multilang_value('inspection_info', lang)
            rec.address_china = self._get_multilang_value('address_china', lang)
            rec.address_tunisia = self._get_multilang_value('address_tunisia', lang)

    def _get_multilang_value(self, field_name, lang):
        defaults = {
            'tech_doc': {
                'fr_FR': "Fournir le document sous Illustrator avec couleurs Pantone",
                'zh_CN': "请提供带潘通颜色的Illustrator文档",
                'en_US': "Provide document in Illustrator with Pantone colors",
            },
            'delivery_info': {
                'fr_FR': "Livraison gratuite à 1 point en France métropolitaine dès 1 000€ HT, options exclues",
                'zh_CN': "法国大陆1个点免费送货，起价1000欧元不含税，不含选项",
                'en_US': "Free delivery to 1 point France mainland from €1,000 excl. tax, without options",
            },
            'payment_info': {
                'fr_FR': "30 jours fin de mois à compter de la date de facture",
                'zh_CN': "发票日期起30天内付款",
                'en_US': "30 days end of month from invoice date",
            },
            'validity_info': {
                'fr_FR': "Offre valable deux semaines",
                'zh_CN': "报价有效期为两周",
                'en_US': "Offer valid for two weeks",
            },
            'delay_info': {
                'fr_FR': "Indiqué sur le devis, hors cas de force majeure",
                'zh_CN': "报价中注明，不包括不可抗力情况",
                'en_US': "Indicated on the quote and does not include force majeure cases",
            },
            'inspection_info': {
                'fr_FR': "Nos inspections respectent l’AQL des standards internationaux ANSI/ASQ Z1.4-2003 / ISO 2859/1",
                'zh_CN': "我们的检验符合国际标准 ANSI/ASQ Z1.4-2003 / ISO 2859/1 的 AQL",
                'en_US': "Our inspections comply with AQL of international standards ANSI/ASQ Z1.4-2003 / ISO 2859/1",
            },
            'address_china': {
                'fr_FR': "313 à 315, Bloc C, Hong Wan Business Center Gushu, Bao’an Area, Shenzhen, Chine",
                'zh_CN': "中国深圳宝安区古墟鸿湾商务中心C栋313至315号",
                'en_US': "313 to 315, Block C, Hong Wan Business Center Gushu, Bao’an Area, Shenzhen, China",
            },
            'address_tunisia': {
                'fr_FR': "Boulevard 14 Janvier, Immeuble Elbahri, 4011 Hammam Sousse",
                'zh_CN': "突尼斯哈马姆苏塞14 Janvier大道, Elbahri大楼, 4011",
                'en_US': "Boulevard 14 Janvier, Elbahri Building, 4011 Hammam Sousse",
            },
            'consigne': {
                'fr_FR': "Fournir le document sous Illustrator avec couleurs Pantone",
                'zh_CN': "请提供带潘通颜色的Illustrator文档",
                'en_US': "Provide document in Illustrator with Pantone colors",
            },
            'delivery_addr': {
                'fr_FR': "Fournir le document sous Illustrator avec couleurs Pantone",
                'zh_CN': "请提供带潘通颜色的Illustrator文档",
                'en_US': "Provide document in Illustrator with Pantone colors",
            },
        }
        return defaults.get(field_name, {}).get(lang, defaults.get(field_name, {}).get('en_US', ''))
    date_b = fields.Text('Date BL')
    date_liv = fields.Text('Date Livraison')

RATES = {
    "EUR": 1.0,
    "USD": 1.157100,
    "CNY": 8.237700,
    "CNH": 8.210959,
    "TND": 3.4015637,
}
class SaleOrderLineInherit(models.Model):
    _inherit = "sale.order.line"
    base_price_eur = fields.Float(
        string='Base Price',
        help="Prix de référence stocké en devise EUR",
    )

    @api.onchange('price_unit')
    def _onchange_price_unit(self):
        """Quand l'utilisateur modifie price_unit dans l'UI : mettre à jour base_price_eur."""
        for line in self:
            order = line.order_id
            if not order:
                continue
            src = order.currency_id and order.currency_id.name or 'EUR'
            if src == 'EUR':
                line.base_price_eur = line.price_unit
            else:
                rate_src = RATES.get(src)
                if rate_src:
                    line.base_price_eur = line.price_unit / rate_src
                else:
                    try:
                        line.base_price_eur = line.price_unit / order.currency_id.rate
                    except Exception:
                        pass

    @api.model_create_multi
    def create(self, vals_list):
        """Lors de la création via API/import — calculer base_price_eur si price_unit fourni."""
        for vals in vals_list:
            if 'price_unit' in vals and 'base_price_eur' not in vals:
                order_id = vals.get('order_id')
                if order_id:
                    order = self.env['sale.order'].browse(order_id)
                    src = order.currency_id and order.currency_id.name or 'EUR'
                    if src == 'EUR':
                        vals['base_price_eur'] = vals['price_unit']
                    else:
                        rate_src = RATES.get(src)
                        if rate_src:
                            vals['base_price_eur'] = vals['price_unit'] / rate_src
        return super(SaleOrderLineInherit, self).create(vals_list)

    def write(self, vals):
        """Quand on sauvegarde (write) — si price_unit change, mettre à jour base_price_eur."""
        lines = self
        if 'price_unit' in vals:
            for line in lines:
                new_price = vals.get('price_unit')
                order = line.order_id
                if not order:
                    continue
                src = order.currency_id and order.currency_id.name or 'EUR'
                if src == 'EUR':
                    vals_to_write = vals.copy()
                    vals_to_write['base_price_eur'] = new_price
                    super(SaleOrderLineInherit, line).write(vals_to_write)
                else:
                    rate_src = RATES.get(src)
                    if rate_src:
                        vals_to_write = vals.copy()
                        vals_to_write['base_price_eur'] = new_price / rate_src
                        super(SaleOrderLineInherit, line).write(vals_to_write)
                    else:
                        super(SaleOrderLineInherit, line).write(vals)
            return True
        else:
            return super(SaleOrderLineInherit, self).write(vals)


    delai_bat = fields.Char(string="Délai Bat", compute='_compute_stock_info', store=True)
    delai_livraison = fields.Char(string="Délai de livraison", compute='_compute_stock_info', store=True)
    print_in_quote = fields.Boolean(string="Imprimer ce produit sur le devis")

    def _compute_stock_info(self):
        for line in self:
            picking = line.order_id.picking_ids[:1]  # premier picking lié à la commande
            if picking:
                line.delai_bat = picking.scheduled_date or ''
                line.delai_livraison = picking.date_done or ''
            else:
                line.delai_bat = ''
                line.delai_livraison = ''


class AccountMove(models.Model):
    _inherit = "account.move"
