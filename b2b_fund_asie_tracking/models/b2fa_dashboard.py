# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2faDashboard(models.AbstractModel):
    _name = 'b2fa.dashboard'
    _description = "Tableau de bord Devis & Commandes"

    # (code, label, icon, couleur principale, couleur secondaire pour dégradé)
    # Palette alignée sur la charte Objets Design (noir + turquoise clair du logo),
    # avec l'or "Fund Raising" conservé comme troisième accent pour la lisibilité.
    #
    # NB : 'b2b' et 'fund' partagent les modèles b2fa.quote / b2fa.order
    # (filtrés par activity_type) ; 'asie' est lu depuis les modèles
    # totalement indépendants b2fa.quote.asie / b2fa.order.asie — aucune
    # relation Odoo entre les deux groupes de modèles.
    _ACTIVITIES = [
        ('b2b', 'B2B Classique', 'fa-briefcase', '#26292E', '#6B6F76'),
        ('fund', 'Fund Raising', 'fa-handshake-o', '#C8790A', '#F2B450'),
        ('asie', 'Asie', 'fa-ship', '#2F94A8', '#8AD2DE'),
    ]

    def _aggregate(self, quotes, orders):
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

    def _section_data(self, code):
        """Retourne (data, quotes, orders) pour une activité donnée. B2B et
        Fund Raising lisent b2fa.quote/b2fa.order (filtrés par activity_type) ;
        Asie lit b2fa.quote.asie/b2fa.order.asie (modèles séparés, jamais
        filtrés puisqu'ils ne contiennent QUE de l'Asie)."""
        if code == 'asie':
            quotes = self.env['b2fa.quote.asie'].search([])
            orders = self.env['b2fa.order.asie'].search([])
        else:
            quotes = self.env['b2fa.quote'].search([('activity_type', '=', code)])
            orders = self.env['b2fa.order'].search([('activity_type', '=', code)])
        return self._aggregate(quotes, orders), quotes, orders

    def _state_distribution(self, records):
        if not records:
            return {}
        labels = dict(records._fields['state'].selection)
        dist = {}
        for key, label in labels.items():
            count = len(records.filtered(lambda r, k=key: r.state == k))
            if count:
                dist[label] = count
        return dist

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

        total_quotes_count = 0
        total_accepted_count = 0
        global_ca_total = 0.0
        global_solde_total = 0.0
        global_acomptes_total = 0.0
        global_orders_count = 0
        global_litige_total = 0
        order_status_distribution = {}
        quote_status_distribution = {}

        for code, label, icon, color, color_soft in self._ACTIVITIES:
            data, quotes, orders = self._section_data(code)
            data.update({'code': code, 'label': label, 'icon': icon, 'color': color, 'color_soft': color_soft})
            result['sections'].append(data)

            total_quotes_count += len(quotes)
            total_accepted_count += len(quotes.filtered(lambda q: q.state == 'accepte'))
            global_ca_total += sum(orders.mapped('amount_ht'))
            global_solde_total += sum(orders.mapped('balance_due'))
            global_acomptes_total += sum(orders.mapped('deposit_received'))
            global_orders_count += len(orders)
            global_litige_total += len(orders.filtered(lambda o: o.state == 'litige'))

            # Les libellés de statut (Selection) sont identiques entre
            # b2fa.order/b2fa.order.asie et b2fa.quote/b2fa.quote.asie : les
            # distributions peuvent donc être fusionnées par libellé, même si
            # les enregistrements viennent de modèles différents.
            for lbl, cnt in self._state_distribution(orders).items():
                order_status_distribution[lbl] = order_status_distribution.get(lbl, 0) + cnt
            for lbl, cnt in self._state_distribution(quotes).items():
                quote_status_distribution[lbl] = quote_status_distribution.get(lbl, 0) + cnt

        conversion_rate = (total_accepted_count / total_quotes_count * 100.0) if total_quotes_count else 0.0

        result['global'] = {
            'ca_total': global_ca_total,
            'solde_total': global_solde_total,
            'acomptes_total': global_acomptes_total,
            'total_quotes': total_quotes_count,
            'conversion_rate': round(conversion_rate, 1),
            'total_orders': global_orders_count,
            'litige_total': global_litige_total,
        }

        result['charts'] = {
            'activity_labels': [s['label'] for s in result['sections']],
            'amount_quotes_by_activity': [s['quotes']['amount_total'] for s in result['sections']],
            'ca_orders_by_activity': [s['orders']['ca_total'] for s in result['sections']],
            'order_status_distribution': order_status_distribution,
            'quote_status_distribution': quote_status_distribution,
        }
        return result
