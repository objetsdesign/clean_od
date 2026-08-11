# models/mrp_production.py
from odoo import models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _cleanup_related_records(self):
        """Nettoyage bas niveau : interroge directement PostgreSQL pour
        trouver toutes les contraintes de clé étrangère (peu importe le
        module) qui pointent vers mrp_production(id), et les neutralise :
        - colonnes ON DELETE CASCADE : rien à faire, gérées par la DB
        - autres colonnes (RESTRICT / NO ACTION / SET NULL) : on tente de
          mettre la colonne à NULL ; si la colonne est NOT NULL en base
          (donc champ obligatoire), on supprime directement la ligne.
        """
        cr = self.env.cr
        cr.execute("""
            SELECT
                tc.table_name,
                kcu.column_name,
                rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            JOIN information_schema.referential_constraints rc
                ON tc.constraint_name = rc.constraint_name
                AND tc.table_schema = rc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND ccu.table_name = 'mrp_production'
                AND ccu.column_name = 'id'
                AND tc.table_name != 'mrp_production'
        """)
        constraints = cr.fetchall()

        ids_tuple = tuple(self.ids)

        for table_name, column_name, delete_rule in constraints:
            if delete_rule == 'CASCADE':
                # déjà géré automatiquement par PostgreSQL
                continue
            try:
                with cr.savepoint():
                    cr.execute(
                        'UPDATE "%s" SET "%s" = NULL WHERE "%s" IN %%s'
                        % (table_name, column_name, column_name),
                        (ids_tuple,)
                    )
            except Exception:
                # la colonne est probablement NOT NULL (champ obligatoire) :
                # on supprime alors carrément la ligne qui bloque
                try:
                    with cr.savepoint():
                        cr.execute(
                            'DELETE FROM "%s" WHERE "%s" IN %%s'
                            % (table_name, column_name),
                            (ids_tuple,)
                        )
                except Exception:
                    pass

        # on a modifié la base hors ORM : on invalide le cache pour éviter
        # des données obsolètes en mémoire
        self.env.invalidate_all()

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
