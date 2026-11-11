"""•	À la confirmation d'une commande client (sale.order) contenant un produit marqué « Fabriqué à l'atelier » (nouveau champ booléen sur product.template), créer automatiquement un ordre d'atelier lié"""
from odoo import _, fields, models, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fabrique_atelier = fields.Boolean(
        string="Fabriqué à l'atelier",
        default=False,
    )


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    atelier_ordre_ids = fields.One2many(
        comodel_name='atelier.ordre',
        inverse_name='sale_order_id',
        string="Ordres d'atelier",
    )

    atelier_ordre_count = fields.Integer(
        string="Nombre d'ordres d'atelier",
        compute='_compute_atelier_ordre_count',
    )

    @api.depends('atelier_ordre_ids')
    def _compute_atelier_ordre_count(self):
        for order in self:
            order.atelier_ordre_count = len(order.atelier_ordre_ids)

    def action_view_atelier_ordres(self):
        self.ensure_one()
        action = {
            'name': _("Ordres d'atelier"),
            'type': 'ir.actions.act_window',
            'res_model': 'atelier.ordre',
            'view_mode': 'list,form,kanban',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }
        if len(self.atelier_ordre_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.atelier_ordre_ids.id,
            })
        return action

    def action_confirm(self):
        res = super().action_confirm()
        AtelierOrdre = self.env['atelier.ordre']

        for order in self:
            lignes_atelier = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id.fabrique_atelier
            )
            if lignes_atelier:
                ordre = AtelierOrdre.create({
                    'name': _("Atelier - %s", order.name),
                    'sale_order_id': order.id,
                    'company_id': order.company_id.id,
                    'date_debut': fields.Datetime.now(),
                    'date_livraison_prevue': order.commitment_date or False,
                })
                order.message_post(
                    body=_("Ordre d'atelier créé automatiquement : %s", ordre.name)
                )
        return res
