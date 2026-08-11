# models/mrp_production.py
from odoo import models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_force_delete(self):
        self.ensure_one()

        moves = self.move_raw_ids | self.move_finished_ids

        # suppression des écritures de valorisation liées aux mouvements
        self.env['stock.valuation.layer'].sudo().search([
            ('stock_move_id', 'in', moves.ids)
        ]).unlink()

        # dé-réservation des mouvements
        for move in moves:
            move._do_unreserve()

        moves.write({'state': 'draft'})

        # suppression des ordres de travail et de leurs relevés de temps
        workorders = self.workorder_ids
        self.env['mrp.workcenter.productivity'].sudo().search([
            ('workorder_id', 'in', workorders.ids)
        ]).unlink()
        workorders.unlink()

        self.write({'state': 'draft'})

        moves.mapped('move_line_ids').unlink()
        moves.unlink()

        self.unlink()

        # ✅ REDIRECTION PROPRE
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manufacturing Orders',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'target': 'current',
        }
