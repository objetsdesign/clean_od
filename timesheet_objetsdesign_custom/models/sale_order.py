from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    opportunity_id = fields.Many2one('crm.lead', string="Opportunité CRM", copy=False)

    def _ensure_pipeline_stages(self):
        """Créer les stages du pipeline si ils n'existent pas"""
        stage_order = ["Nouvelle demande de devis", "Contact initial", "Démonstration", "Devis envoyé", "Négociation",
                       "Clôture"]
        for name in stage_order:
            stage = self.env['crm.stage'].search([('name', '=', name)], limit=1)
            if not stage:
                self.env['crm.stage'].create({
                    'name': name,
                    'sequence': stage_order.index(name) + 1,
                })

    def create_or_link_opportunity(self):
        """Créer l'opportunité si elle n'existe pas et assigner le premier stage du pipeline"""
        self._ensure_pipeline_stages()  # Crée les stages si nécessaire

        for order in self:
            if not order.opportunity_id:
                stage_initial = self.env['crm.stage'].sudo().search([('name', '=', 'Nouvelle demande de devis')], limit=1)
                opportunity = self.env['crm.lead'].sudo().create({
                    'name': f"Nouvelle demande de devis - {order.partner_id.name}",
                    'partner_id': order.partner_id.id,
                    'type': 'opportunity',
                    'stage_id': stage_initial.id if stage_initial else False,
                })
                order.opportunity_id = opportunity.id

    def action_confirm(self):
        """Créer ou lier l'opportunité sans changer le stage"""
        self.create_or_link_opportunity()
        return super().action_confirm()

    def action_advance_pipeline(self):
        """Avancer l'opportunité au stage suivant"""
        stage_order = ["Nouvelle demande", "Contact initial", "Démonstration", "Devis envoyé", "Négociation", "Clôture"]
        for order in self:
            if order.opportunity_id and order.opportunity_id.stage_id:
                current_name = order.opportunity_id.stage_id.name
                if current_name in stage_order:
                    index = stage_order.index(current_name)
                    if index + 1 < len(stage_order):
                        next_stage = self.env['crm.stage'].search([('name', '=', stage_order[index + 1])], limit=1)
                        if next_stage:
                            order.opportunity_id.stage_id = next_stage.id

    @api.model
    def _create_invoices_acompte(self):
        for order in self:
            normal_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': order.partner_id.id,
                'invoice_origin': order.name,
                'invoice_line_ids': [(0, 0, {
                    'name': line.name,
                    'quantity': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'tax_ids': [(6, 0, line.tax_id.ids)],
                    'product_id': line.product_id.id,
                    'account_id': line.product_id.categ_id.property_account_income_categ_id.id,
                }) for line in order.order_line],
            })

            acompte_percentage = 40
            if acompte_percentage > 0:
                total_ht = normal_invoice.amount_untaxed
                acompte_ht = total_ht * (acompte_percentage / 100)

                tax_20 = self.env['account.tax'].search([('amount', '=', 20), ('type_tax_use', '=', 'sale')], limit=1)

                acompte_invoice = self.env['account.move'].create({
                    'move_type': 'out_invoice',
                    'partner_id': order.partner_id.id,
                    'invoice_origin': order.name,
                    'is_downpayment_invoice': True,
                    'related_invoice_id': normal_invoice.id,
                    'invoice_line_ids': [
                        (0, 0, {
                            'name': "Montant total HT (référence)",
                            'quantity': 1,
                            'price_unit': total_ht,
                            'account_id': normal_invoice.invoice_line_ids[0].account_id.id,
                        }),
                        (0, 0, {
                            'name': f"Acompte {acompte_percentage}%",
                            'quantity': 1,
                            'price_unit': acompte_ht,
                            'tax_ids': [(6, 0, [tax_20.id])] if tax_20 else [],
                            'account_id': normal_invoice.invoice_line_ids[0].account_id.id,
                        })
                    ]
                })

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    image_128 = fields.Image("Miniature", max_width=128, max_height=128)
