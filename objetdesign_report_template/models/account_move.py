from datetime import date

from odoo import models, fields, api,_
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'
    acompte_amount = fields.Float(string="Montant d'acompte (%)", store=True)
    is_acompte_forced_display = fields.Boolean(string="Forcer l'affichage de l'acompte")
    delivery = fields.Text(string="Delivery")
    issuer = fields.Text("Issuer")
    file_no = fields.Text("File N°")
    show_conditions_tab = fields.Boolean(
        string="Afficher Conditions", compute="_compute_show_conditions_tab", store=True
    )

    @api.depends('partner_id', 'partner_id.category_id')
    def _compute_show_conditions_tab(self):
        for move in self:
            if move.partner_id:
                move.show_conditions_tab = any(cat.name == "B2B" for cat in move.partner_id.category_id)
            else:
                move.show_conditions_tab = False
    partner_ref_related = fields.Char(
        string="Référence partenaire",
        related="partner_id.partner_ref",
        store=True,
        readonly=True
    )
    sale_order_ref = fields.Char(
        string="Devis lié",
        compute="_compute_sale_order_ref",
        store=False
    )
    purchase_id = fields.Many2one(
        'purchase.order',
        string='Référence Commande Fournisseur',
        compute='_compute_references',
        store=True,
        readonly=True
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Référence Devis Client',
        compute='_compute_references',
        store=True,
        readonly=True
    )

    @api.depends('invoice_origin')
    def _compute_references(self):
        """
        Remplit automatiquement la référence commande fournisseur ou commande client
        en fonction du champ 'invoice_origin'.
        """
        for move in self:
            purchase = self.env['purchase.order'].search([('name', '=', move.invoice_origin)], limit=1)
            if purchase:
                move.purchase_id = purchase
                move.sale_order_id = purchase.sale_order_id.id if purchase.sale_order_id else False
                continue  # On ne cherche pas une commande client si on a trouvé une commande fournisseur

            sale = self.env['sale.order'].search([('name', '=', move.invoice_origin)], limit=1)
            if sale:
                move.sale_order_id = sale
                move.purchase_id = False
            else:
                move.purchase_id = False
                move.sale_order_id = False



    def _compute_sale_order_ref(self):
        for move in self:
            sale_orders = move.invoice_line_ids.mapped('sale_line_ids.order_id')
            move.sale_order_ref = ', '.join(sale_orders.mapped('name'))
