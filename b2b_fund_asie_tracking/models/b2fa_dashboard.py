# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2faDashboard(models.AbstractModel):
    _name = 'b2fa.dashboard'
    _description = "Tableau de bord Devis & Commandes"

    _ACTIVITIES = [
        ('b2b', 'B2B Classique', 'fa-briefcase', '#3B82F6'),
        ('fund', 'Fund Raising', 'fa-handshake-o', '#8B5CF6'),
        ('asie', 'Asie', 'fa-globe', '#F59E0B'),
    ]

    def _section_data(self, activity):
        Quote = self.env['b2fa.quote']
        Order = self.env['b2fa.order']

        quotes = Quote.search([('activity_type', '=', activity)])
        orders = Order.search([('activity_type', '=', activity)])

        total_quotes = len(quotes)
        accepted = quotes.filtered(lambda q: q.state == 'accepte')
        refused = quotes.filtered(lambda q: q.state == 'refuse')
        pending = quotes - accepted - refused
        conversion_rate = (len(accepted) / total_quotes * 100.0) if total_quotes else 0.0

        total_orders = len(orders)
        en_production = orders.filtered(lambda o: o.state == 'en_production')
        expediees = orders.filtered(lambda o: o.state == 'expediee')
        livrees = orders.filtered(lambda o: o.state == 'livree')
        litige = orders.filtered(lambda o: o.state == 'litige')

        return {
            'quotes': {
                'total': total_quotes,
                'accepted': len(accepted),
                'refused': len(refused),
                'pending': len(pending),
                'conversion_rate': round(conversion_rate, 1),
                'amount_total': sum(quotes.mapped('amount')),
                'amount_accepted': sum(accepted.mapped('amount')),
            },
            'orders': {
                'total': total_orders,
                'en_production': len(en_production),
                'expediees': len(expediees),
                'livrees': len(livrees),
                'litige': len(litige),
                'ca_total': sum(orders.mapped('amount_ht')),
                'acomptes': sum(orders.mapped('deposit_received')),
                'solde': sum(orders.mapped('balance_due')),
            },
        }

    @api.model
    def get_dashboard_data(self):
        currency = self.env.company.currency_id
        result = {
            'currency_symbol': currency.symbol,
            'currency_position': currency.position,
            'sections': [],
            'global': {},
            'charts': {},
        }

        all_orders = self.env['b2fa.order']
        all_quotes = self.env['b2fa.quote']

        for code, label, icon, color in self._ACTIVITIES:
            data = self._section_data(code)
            data.update({'code': code, 'label': label, 'icon': icon, 'color': color})
            result['sections'].append(data)
            all_orders |= self.env['b2fa.order'].search([('activity_type', '=', code)])
            all_quotes |= self.env['b2fa.quote'].search([('activity_type', '=', code)])

        total_quotes = len(all_quotes)
        accepted = all_quotes.filtered(lambda q: q.state == 'accepte')
        conversion_rate = (len(accepted) / total_quotes * 100.0) if total_quotes else 0.0

        result['global'] = {
            'ca_total': sum(all_orders.mapped('amount_ht')),
            'solde_total': sum(all_orders.mapped('balance_due')),
            'acomptes_total': sum(all_orders.mapped('deposit_received')),
            'total_quotes': total_quotes,
            'conversion_rate': round(conversion_rate, 1),
            'total_orders': len(all_orders),
            'litige_total': len(all_orders.filtered(lambda o: o.state == 'litige')),
        }

        order_state_labels = dict(self.env['b2fa.order']._fields['state'].selection)
        order_status_distribution = {}
        for key, label in order_state_labels.items():
            count = len(all_orders.filtered(lambda o, k=key: o.state == k))
            if count:
                order_status_distribution[label] = count

        quote_state_labels = dict(self.env['b2fa.quote']._fields['state'].selection)
        quote_status_distribution = {}
        for key, label in quote_state_labels.items():
            count = len(all_quotes.filtered(lambda q, k=key: q.state == k))
            if count:
                quote_status_distribution[label] = count

        result['charts'] = {
            'activity_labels': [s['label'] for s in result['sections']],
            'amount_quotes_by_activity': [s['quotes']['amount_total'] for s in result['sections']],
            'ca_orders_by_activity': [s['orders']['ca_total'] for s in result['sections']],
            'order_status_distribution': order_status_distribution,
            'quote_status_distribution': quote_status_distribution,
        }
        return result
