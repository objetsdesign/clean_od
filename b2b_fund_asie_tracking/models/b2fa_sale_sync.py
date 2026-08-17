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

    def _base_vals(self, so):
        """Champs communs, indépendants du modèle Quote/Order cible."""
        description = self._build_description(so)
        qty = self._compute_qty(so)
        date_order = so.date_order.date() if so.date_order else False
        return description, qty, date_order

    def _sync_generic(self, so, Quote, Order, current_quote, current_order, link_writer, activity=None):
        """Synchronise `so` (sale.order) vers un couple de modèles Quote/Order
        donné (b2fa.quote/b2fa.order pour B2B & Fund Raising, OU
        b2fa.quote.asie/b2fa.order.asie pour Asie — jamais mélangés). Si
        `activity` est fourni, il est écrit dans le champ partagé
        'activity_type' (seulement pertinent pour b2fa.quote/b2fa.order).
        `link_writer(quote, order)` décide où persister le lien vers les
        enregistrements créés/mis à jour (sur sale.order pour B2B/Fund, sur
        sale.order.sky pour Asie).
        """
        stats = dict.fromkeys(_STATS_KEYS, 0)
        description, qty, date_order = self._base_vals(so)

        # --- Devis (toujours synchronisé, quel que soit le statut Ventes) ---
        quote_vals = {
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
        if activity is not None:
            quote_vals['activity_type'] = activity

        if current_quote:
            current_quote.write(quote_vals)
            quote = current_quote
            stats['quotes_updated'] += 1
        else:
            quote = Quote.create(quote_vals)
            stats['quotes_created'] += 1

        # --- Commande (uniquement une fois le devis Ventes confirmé) ---
        order = current_order
        if so.state in ('sale', 'done'):
            order_vals = {
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
            if activity is not None:
                order_vals['activity_type'] = activity

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
        """Point d'entrée unique, toutes activités confondues. Lit
        b2fa_activity_type sur sale.order et route chaque commande vers le
        bon couple de modèles :
        - 'b2b' / 'fund' -> b2fa.quote / b2fa.order (modèles partagés,
          filtrés par activity_type) ;
        - 'asie' -> b2fa.quote.asie / b2fa.order.asie (modèles totalement
          indépendants, sans relation avec b2fa.quote/b2fa.order), via une
          fiche sale.order.sky créée/retrouvée automatiquement pour porter
          le lien.
        Idempotent (matché via sale_order_id) : les champs propres au suivi
        (production, transport...) ne sont jamais écrasés une fois la
        commande créée.
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

        shared_orders = self.env['sale.order']
        asie_orders = self.env['sale.order']
        for so in orders:
            if so.b2fa_activity_type in ('b2b', 'fund'):
                shared_orders |= so
            elif so.b2fa_activity_type == 'asie':
                asie_orders |= so
            else:
                stats['skipped_unclassified'] += 1

        Quote = self.env['b2fa.quote']
        Order = self.env['b2fa.order']
        for so in shared_orders:
            def _link_writer(quote, order, so=so):
                vals = {}
                if quote and so.b2fa_quote_id != quote:
                    vals['b2fa_quote_id'] = quote.id
                if order and so.b2fa_order_id != order:
                    vals['b2fa_order_id'] = order.id
                if vals:
                    so.with_context(b2fa_no_autosync=True).write(vals)

            frag = self._sync_generic(so, Quote, Order, so.b2fa_quote_id, so.b2fa_order_id,
                                       _link_writer, activity=so.b2fa_activity_type)
            for key in _STATS_KEYS:
                stats[key] += frag[key]

        if asie_orders:
            Sky = self.env['sale.order.sky']
            existing = Sky.search([('sale_order_id', 'in', asie_orders.ids)])
            existing_ids = set(existing.mapped('sale_order_id.id'))
            to_create = asie_orders.filtered(lambda so: so.id not in existing_ids)
            new_skies = Sky
            if to_create:
                # b2fa_no_autosync : on synchronise nous-mêmes juste après
                # (run_sync_sky), pas besoin que sale.order.sky.create() le
                # refasse en double.
                new_skies = Sky.with_context(b2fa_no_autosync=True).create(
                    [{'sale_order_id': so.id} for so in to_create])
            asie_stats = self.run_sync_sky(sky_records=existing | new_skies)
            for key in _STATS_KEYS:
                stats[key] += asie_stats[key]

        return stats

    @api.model
    def run_sync_sky(self, sky_records=None):
        """Synchronise les fiches sale.order.sky (classification Asie) vers
        b2fa.quote.asie / b2fa.order.asie — modèles totalement séparés de
        b2fa.quote / b2fa.order. Ne lit ni n'écrit jamais sur sale.order :
        uniquement sur sale.order.sky."""
        Quote = self.env['b2fa.quote.asie']
        Order = self.env['b2fa.order.asie']
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

            frag = self._sync_generic(so, Quote, Order, sky.b2fa_quote_id, sky.b2fa_order_id, _link_writer)
            for key in _STATS_KEYS:
                stats[key] += frag[key]

        return stats

    @api.model
    def _cron_sync(self):
        self.run_sync()
        # Filet de sécurité supplémentaire : resynchronise aussi les fiches
        # sale.order.sky qui existeraient sans (ou plus) b2fa_activity_type
        # = 'asie' sur leur commande Ventes liée (import en masse direct sur
        # sale.order.sky, changement manuel du champ, etc.).
        self.run_sync_sky()
