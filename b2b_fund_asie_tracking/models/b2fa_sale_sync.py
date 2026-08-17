# -*- coding: utf-8 -*-
from odoo import api, models

QUOTE_STATE_MAP = {
    'draft': 'en_cours',
    'sent': 'envoye',
    'sale': 'accepte',
    'done': 'accepte',
    'cancel': 'refuse',
}

_STATS_KEYS = ('quotes_created', 'quotes_updated', 'orders_created', 'orders_updated')


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

    def _sync_one(self, so, activity, current_quote, current_order, link_writer):
        """Sync a single sale.order into b2fa.quote / b2fa.order for the given
        activity. `current_quote` / `current_order` are the b2fa.quote /
        b2fa.order records currently linked (or empty recordsets). `link_writer`
        is called with (quote, order) so the CALLER decides where the link is
        persisted — on sale.order for b2b/fund, on sale.order.sky for asie —
        this method itself never writes on sale.order.
        """
        Quote = self.env['b2fa.quote']
        Order = self.env['b2fa.order']
        stats = dict.fromkeys(_STATS_KEYS, 0)

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
        if current_quote:
            current_quote.write(quote_vals)
            quote = current_quote
            stats['quotes_updated'] += 1
        else:
            quote = Quote.create(quote_vals)
            stats['quotes_created'] += 1

        # --- Commande (only once the sale.order is confirmed) ---
        order = current_order
        if so.state in ('sale', 'done'):
            order_vals = {
                'activity_type': activity,
                'client': so.partner_id.name or 'Client non renseigné',
                'description': description,
                'qty': qty,
                'amount_ht': so.amount_untaxed,
                'date_commande': date_order,
                'sale_order_id': so.id,
                'quote_id': quote.id,
                'source_ref': so.name,
                'company_id': so.company_id.id,
            }
            if current_order:
                # Never touch 'state' again: production/shipping tracking is
                # managed manually inside the Suivi Devis & Commandes app.
                current_order.write(order_vals)
                stats['orders_updated'] += 1
            else:
                order_vals['state'] = 'confirmee'
                order = Order.create(order_vals)
                stats['orders_created'] += 1

        link_writer(quote, order)
        return stats

    @api.model
    def run_sync(self, sale_orders=None, activities=None):
        """Push sale.order records classified via b2fa_activity_type (B2B /
        Fund Raising only — Asie never sets this field, see run_sync_sky)
        into b2fa.quote / b2fa.order. Safe to run repeatedly (idempotent,
        matched via sale_order_id): existing b2fa.order production/shipping
        tracking fields are never overwritten once the order exists — only
        the fields that come from Ventes (client, amount, qty, description,
        dates) are refreshed.
        """
        if sale_orders is not None:
            orders = sale_orders
        else:
            domain = [('b2fa_activity_type', '!=', False)]
            if activities:
                domain.append(('b2fa_activity_type', 'in', activities))
            orders = self.env['sale.order'].search(domain)

        unclassified_total = self.env['sale.order'].search_count([('b2fa_activity_type', '=', False)])

        stats = dict.fromkeys(_STATS_KEYS, 0)
        stats.update({'skipped_unclassified': 0, 'unclassified_total': unclassified_total})

        for so in orders:
            if not so.b2fa_activity_type:
                stats['skipped_unclassified'] += 1
                continue

            def _link_writer(quote, order, so=so):
                vals = {}
                if quote and so.b2fa_quote_id != quote:
                    vals['b2fa_quote_id'] = quote.id
                if order and so.b2fa_order_id != order:
                    vals['b2fa_order_id'] = order.id
                if vals:
                    so.with_context(b2fa_no_autosync=True).write(vals)

            frag = self._sync_one(so, so.b2fa_activity_type, so.b2fa_quote_id, so.b2fa_order_id, _link_writer)
            for key in _STATS_KEYS:
                stats[key] += frag[key]

        return stats

    @api.model
    def run_sync_sky(self, sky_records=None):
        """Push 'Asie' classifications tracked on sale.order.sky into
        b2fa.quote / b2fa.order. This is the ONLY sync path used for the
        'asie' activity: it never reads or writes anything on sale.order —
        only on sale.order.sky, so the Ventes order stays untouched while the
        dashboard's Asie section is still fed."""
        Sky = self.env['sale.order.sky']
        skies = sky_records if sky_records is not None else Sky.search([])

        stats = dict.fromkeys(_STATS_KEYS, 0)

        for sky in skies:
            so = sky.sale_order_id
            if not so:
                continue

            def _link_writer(quote, order, sky=sky):
                vals = {}
                if quote and sky.b2fa_quote_id != quote:
                    vals['b2fa_quote_id'] = quote.id
                if order and sky.b2fa_order_id != order:
                    vals['b2fa_order_id'] = order.id
                if vals:
                    sky.with_context(b2fa_no_autosync=True).write(vals)

            frag = self._sync_one(so, 'asie', sky.b2fa_quote_id, sky.b2fa_order_id, _link_writer)
            for key in _STATS_KEYS:
                stats[key] += frag[key]

        return stats

    @api.model
    def _cron_sync(self):
        self.run_sync()
        self.run_sync_sky()
