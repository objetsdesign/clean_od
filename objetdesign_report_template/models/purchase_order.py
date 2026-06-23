from odoo import models, fields, api, _
from odoo.exceptions import UserError

RATES = {
    "EUR": 1.0,
    "USD": 1.157100,
    "CNY": 8.237700,
    "CNH": 8.210959,
    "TND": 3.4015637,
}
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    show_conditions_tab = fields.Boolean(
        string="Afficher Conditions", compute="_compute_show_conditions_tab", store=True
    )
    @api.depends('partner_id', 'partner_id.category_id')
    def _compute_show_conditions_tab(self):
        for order in self:
            if order.partner_id:
                order.show_conditions_tab = any(cat.name == "B2B" for cat in order.partner_id.category_id)
            else:
                order.show_conditions_tab = False
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Référence Devis',
        readonly=True
    )
    partner_ref_related = fields.Char(
        string="Référence partenaire",
        related="partner_id.partner_ref",
        store=True,
        readonly=True
    )
    has_active_pricelist = fields.Boolean(compute='_compute_has_active_pricelist')
    show_update_pricelist = fields.Boolean(default=True)
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        domain="[('company_id','=',company_id)]"
    )

    @api.depends('company_id')
    def _compute_has_active_pricelist(self):
        for order in self:
            order.has_active_pricelist = bool(
                self.env['product.pricelist'].search(
                    [('active', '=', True), ('company_id', '=', order.company_id.id)],
                    limit=1
                )
            )

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

        src_currency = self.currency_id.name
        tgt_currency = self.pricelist_id.currency_id.name
        rate_src = rates.get(src_currency) or 1.0
        rate_tgt = rates.get(tgt_currency) or 1.0

        for line in self.order_line:
            if not line.product_id:
                continue

            line.base_price_eur = line.price_unit / rate_src

            line.price_unit = line.base_price_eur * rate_tgt

            if hasattr(line, "_compute_amount"):
                line._compute_amount()

        self.currency_id = self.pricelist_id.currency_id

    def action_rfq_send(self):
        """Override pour utiliser un template mail personnalisé"""
        self.ensure_one()

        res = super(PurchaseOrder, self).action_rfq_send()

        ctx = res.get('context', {})

        if self.env.context.get('send_rfq', False):
            template = self.env.ref('objetdesign_report_template.email_template_edi_purchase_02',
                                    raise_if_not_found=False)
        else:
            template = self.env.ref('objetdesign_report_template.email_template_edi_purchase_02',
                                    raise_if_not_found=False)

        if template:
            ctx['default_template_id'] = template.id

        res['context'] = ctx

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
    delivery_addr = fields.Text(string="Delivery Address",
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
        }
        return defaults.get(field_name, {}).get(lang, defaults.get(field_name, {}).get('en_US', ''))
    date_b = fields.Text('Date BL')
    date_liv = fields.Text('Date Livraison')


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    base_price_eur  = fields.Float(
        string="Prix de base",
        help="Prix de référence pour la conversion de devises",
    )

    @api.onchange('price_unit')
    def _onchange_price_unit(self):
        """Si l'utilisateur modifie price_unit manuellement, mettre à jour base_price_eur"""
        for line in self:
            order = line.order_id
            if not order:
                continue
            src = order.currency_id.name
            if src == 'EUR':
                line.base_price_eur = line.price_unit
            else:
                rate_src = RATES.get(src) or 1.0
                line.base_price_eur = line.price_unit / rate_src

    def write(self, vals):
        """Si price_unit change via write(), mettre à jour base_price_eur"""
        if 'price_unit' in vals:
            for line in self:
                order = line.order_id
                if not order:
                    continue
                src = order.currency_id.name
                new_price = vals['price_unit']
                if src == 'EUR':
                    vals['base_price_eur'] = new_price
                else:
                    rate_src = RATES.get(src) or 1.0
                    vals['base_price_eur'] = new_price / rate_src
        return super(PurchaseOrderLine, self).write(vals)
