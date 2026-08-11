# models/mrp_production.py
from odoo import models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _cleanup_related_records(self):
        """Recherche dans tout le système les champs many2one pointant vers
        mrp.production et nettoie les enregistrements qui référencent encore
        les OF de self, afin de permettre leur suppression :
        - si le champ est obligatoire, l'enregistrement lié est supprimé
        - sinon, le champ est simplement remis à False
        """
        IrFields = self.env['ir.model.fields'].sudo()
        related_fields = IrFields.search([
            ('relation', '=', 'mrp.production'),
            ('ttype', '=', 'many2one'),
            ('model', '!=', 'mrp.production'),
            ('store', '=', True),
        ])
        for field in related_fields:
            model_name = field.model
            if model_name not in self.env:
                continue
            Model = self.env[model_name].sudo()
            odoo_field = Model._fields.get(field.name)
            if odoo_field is None or not odoo_field.store:
                continue
            try:
                records = Model.search([(field.name, 'in', self.ids)])
            except Exception:
                continue
            if not records:
                continue
            if field.required:
                try:
                    records.unlink()
                except Exception:
                    pass
            else:
                try:
                    records.write({field.name: False})
                except Exception:
                    pass

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

        # nettoyage générique : tout enregistrement d'un autre modèle qui
        # référence encore cet OF (contrôle qualité, unbuild, etc.) est soit
        # supprimé (si le lien est obligatoire) soit dé-lié (sinon), afin
        # d'éviter le blocage "ne peuvent être supprimés" à l'unlink final.
        self._cleanup_related_records()

        self.unlink()

        # ✅ REDIRECTION PROPRE
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manufacturing Orders',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'target': 'current',
        }
