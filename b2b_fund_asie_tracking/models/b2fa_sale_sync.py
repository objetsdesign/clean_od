# -*- coding: utf-8 -*-
from odoo import api, models

QUOTE_STATE_MAP = {
    'draft': 'en_cours',
    'sent': 'envoye',
    'sale': 'accepte',
    'done': 'accepte',
    'cancel': 'refuse',
}


class B2faSaleSync(models.AbstractModel):
    _name = 'b2fa.sale.sync'
    _description = "Synchronisation Ventes -> Suivi Devis & Commandes"

    def _build_description(self, sale_order):
        lines = sale_order.order_line.filtered(lambda l: not l.display_type and l.product_id)
        parts = []
        for line in lines[:20]:
            qty = line.product_uom_qty
            qty_str = ('%g' % qty) if qty else '0'
            parts.append("%s x %s" % (qty_str, line.product_id.name))
        text = ", ".join(parts)
        return text[:2000]

    def _compute_qty(self, sale_order):
        lines = sale_order.order_line.filtered(lambda l: not l.display_type)
        return sum(lines.mapped('product_uom_qty')) or 1.0

    @api.model
    def run_sync(self, sale_orders=None, activities=None):
        """Push classified sale.order records (b2fa_activity_type set) into
        b2fa.quote / b2fa.order. Safe to run repeatedly (idempotent, matched via
        sale_order_id): existing b2fa.order production/shipping tracking fields
        are never overwritten once the order exists — only the fields that come
        from Ventes (client, amount, qty, description, dates) are refreshed.
        """
        Quote = self.env['b2fa.quote']
        Order = self.env['b2fa.order']

        if sale_orders is not None:
            orders = sale_orders
        else:
            domain = [('b2fa_activity_type', '!=', False)]
            if activities:
                domain.append(('b2fa_activity_type', 'in', activities))
            orders = self.env['sale.order'].search(domain)

        unclassified_total = self.env['sale.order'].search_count([('b2fa_activity_type', '=', False)])

        stats = {
            'quotes_created': 0, 'quotes_updated': 0,
            'orders_created': 0, 'orders_updated': 0,
            'skipped_unclassified': 0,
            'unclassified_total': unclassified_total,
        }

        for so in orders:
            if not so.b2fa_activity_type:
                stats['skipped_unclassified'] += 1
                continue

            activity = so.b2fa_activity_type
            description = self._build_description(so)
            qty = self._compute_qty(so)
            date_order = so.date_order.date() if so.date_order else False

            # --- Devis (always synced, whatever the sale.order status) ---
            quote_vals = {
                'activity_type': activity,
                'client': so.partner_id.name or 'Client non renseigné',
                'description': description,
                'qty': qty,
                'amount': so.amount_untaxed,
                'date_devis': date_order,
                'state': QUOTE_STATE_MAP.get(so.state, 'en_cours'),
                'sale_order_id': so.id,
                'source_ref': so.name,
                'company_id': so.company_id.id,
            }
            if so.b2fa_quote_id:
                so.b2fa_quote_id.write(quote_vals)
                stats['quotes_updated'] += 1
            else:
                quote = Quote.create(quote_vals)
                so.with_context(b2fa_no_autosync=True).write({'b2fa_quote_id': quote.id})
                stats['quotes_created'] += 1

            # --- Commande (only once the sale.order is confirmed) ---
            if so.state in ('sale', 'done'):
                order_vals = {
                    'activity_type': activity,
                    'client': so.partner_id.name or 'Client non renseigné',
                    'description': description,
                    'qty': qty,
                    'amount_ht': so.amount_untaxed,
                    'date_commande': date_order,
                    'sale_order_id': so.id,
                    'quote_id': so.b2fa_quote_id.id,
                    'source_ref': so.name,
                    'company_id': so.company_id.id,
                }
                if so.b2fa_order_id:
                    # Never touch 'state' again: production/shipping tracking is
                    # managed manually inside the Suivi Devis & Commandes app.
                    so.b2fa_order_id.write(order_vals)
                    stats['orders_updated'] += 1
                else:
                    order_vals['state'] = 'confirmee'
                    order = Order.create(order_vals)
                    so.with_context(b2fa_no_autosync=True).write({'b2fa_order_id': order.id})
                    stats['orders_created'] += 1

        return stats

    @api.model
    def _cron_sync(self):
        self.run_sync()
