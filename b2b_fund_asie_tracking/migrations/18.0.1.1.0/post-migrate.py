# -*- coding: utf-8 -*-
"""Migration 18.0.1.1.0

Avant cette version, l'activité 'Asie' pouvait exister comme valeur de
activity_type sur b2fa.quote / b2fa.order (modèles partagés avec B2B
Classique / Fund Raising). Depuis cette version, Asie vit sur des modèles
100% séparés : b2fa.quote.asie / b2fa.order.asie.

Cette migration :
1. Recopie chaque b2fa.quote / b2fa.order avec activity_type == 'asie' vers
   b2fa.quote.asie / b2fa.order.asie (même contenu, sans le champ
   activity_type qui n'existe plus sur les nouveaux modèles).
2. Si l'enregistrement d'origine était lié à un sale.order (sale_order_id),
   recrée/complète le lien via une fiche sale.order.sky et met à jour
   b2fa_activity_type = 'asie' sur ce sale.order (cohérent avec le fait
   qu'Asie est de nouveau un choix normal du champ Activité).
3. Supprime les enregistrements d'origine devenus obsolètes dans
   b2fa.quote / b2fa.order (qui ne doivent plus contenir d'Asie).

Idempotente : si elle est relancée, elle ne trouvera plus aucun
activity_type == 'asie' sur b2fa.quote/b2fa.order et ne fera rien.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

_QUOTE_FIELDS = [
    'name', 'date_devis', 'client', 'secteur', 'contact', 'description', 'qty',
    'company_id', 'amount', 'state', 'date_relance_1', 'date_relance_2',
    'date_relance_3', 'reponse_client', 'motif_refus', 'proba_conversion',
    'next_action', 'notes', 'active', 'source_ref', 'sale_order_id',
]

_ORDER_FIELDS = [
    'name', 'date_commande', 'client', 'contact', 'description', 'qty',
    'company_id', 'amount_ht', 'cost', 'deposit_received', 'state',
    'production_source', 'date_prod_prevue', 'date_prod_reelle',
    'date_expedition', 'carrier', 'logistics_fees', 'tracking_number',
    'date_livraison_prevue', 'date_livraison_reelle', 'notes_incidents',
    'active', 'source_ref', 'quote_ref_text', 'sale_order_id',
]


def _copy_vals(record, field_names):
    vals = {}
    for fname in field_names:
        field = record._fields[fname]
        value = record[fname]
        if field.type in ('many2one',):
            vals[fname] = value.id if value else False
        else:
            vals[fname] = value
    return vals


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    if 'b2fa.quote' not in env or 'b2fa.quote.asie' not in env:
        return  # models not present (fresh install / unexpected state) : nothing to do

    Quote = env['b2fa.quote']
    Order = env['b2fa.order']
    QuoteAsie = env['b2fa.quote.asie']
    OrderAsie = env['b2fa.order.asie']
    Sky = env['sale.order.sky']

    old_quotes = Quote.search([('activity_type', '=', 'asie')])
    old_orders = Order.search([('activity_type', '=', 'asie')])

    if not old_quotes and not old_orders:
        return

    _logger.info(
        "b2b_fund_asie_tracking migration: moving %s devis / %s commandes 'Asie' "
        "from b2fa.quote/b2fa.order to b2fa.quote.asie/b2fa.order.asie.",
        len(old_quotes), len(old_orders),
    )

    quote_map = {}  # old b2fa.quote id -> new b2fa.quote.asie record
    for old_quote in old_quotes:
        vals = _copy_vals(old_quote, _QUOTE_FIELDS)
        new_quote = QuoteAsie.with_context(b2fa_no_autosync=True).create(vals)
        quote_map[old_quote.id] = new_quote

    for old_order in old_orders:
        vals = _copy_vals(old_order, _ORDER_FIELDS)
        old_quote_id = old_order.quote_id.id if old_order.quote_id else False
        vals['quote_id'] = quote_map[old_quote_id].id if old_quote_id in quote_map else False
        new_order = OrderAsie.create(vals)

        so = old_order.sale_order_id
        if so:
            if so.b2fa_activity_type != 'asie':
                so.with_context(b2fa_no_autosync=True).write({'b2fa_activity_type': 'asie'})
            sky = Sky.search([('sale_order_id', '=', so.id)], limit=1)
            if not sky:
                sky = Sky.with_context(b2fa_no_autosync=True).create({'sale_order_id': so.id})
            linked_quote = quote_map.get(old_quote_id)
            sky_vals = {'b2fa_order_id': new_order.id}
            if linked_quote:
                sky_vals['b2fa_quote_id'] = linked_quote.id
            sky.with_context(b2fa_no_autosync=True).write(sky_vals)

    # Devis Asie jamais transformés en commande : même traitement, juste le devis.
    for old_quote in old_quotes:
        so = old_quote.sale_order_id
        if not so:
            continue
        if so.b2fa_activity_type != 'asie':
            so.with_context(b2fa_no_autosync=True).write({'b2fa_activity_type': 'asie'})
        sky = Sky.search([('sale_order_id', '=', so.id)], limit=1)
        if not sky:
            sky = Sky.with_context(b2fa_no_autosync=True).create({'sale_order_id': so.id})
        if not sky.b2fa_quote_id:
            sky.with_context(b2fa_no_autosync=True).write({'b2fa_quote_id': quote_map[old_quote.id].id})

    # Nettoyage : on retire d'abord les liens sale.order -> ancien
    # b2fa.quote/b2fa.order avant de les supprimer (b2fa_quote_id / b2fa_order_id
    # sur sale.order sont copy=False, readonly, sans ondelete='cascade' explicite,
    # donc mieux vaut les vider proprement).
    linked_orders = env['sale.order'].search([
        '|', ('b2fa_quote_id', 'in', old_quotes.ids), ('b2fa_order_id', 'in', old_orders.ids),
    ])
    for so in linked_orders:
        vals = {}
        if so.b2fa_quote_id.id in old_quotes.ids:
            vals['b2fa_quote_id'] = False
        if so.b2fa_order_id.id in old_orders.ids:
            vals['b2fa_order_id'] = False
        if vals:
            so.with_context(b2fa_no_autosync=True).write(vals)

    old_orders.unlink()
    old_quotes.unlink()

    _logger.info("b2b_fund_asie_tracking migration: done.")
