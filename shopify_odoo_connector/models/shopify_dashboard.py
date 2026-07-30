# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# États sale.order considérés comme des ventes "réalisées"
SALE_STATES = ("sale", "done")

# Choix de granularité proposés à l'utilisateur
GRANULARITY_TRUNC = {
    "day": "date_order:day",
    "week": "date_order:week",
    "month": "date_order:month",
}


class ShopifyDashboard(models.AbstractModel):
    """Agrège les données de vente Shopify pour le tableau de bord
    statistique (courbes, KPI, tops). Aucune persistance : tout est
    recalculé à la demande via des read_group, donc toujours à jour."""

    _name = "shopify.dashboard"
    _description = "Statistiques du tableau de bord Shopify"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _auto_granularity(self, date_from, date_to):
        nb_days = (date_to - date_from).days or 1
        if nb_days <= 62:
            return "day"
        if nb_days <= 210:
            return "week"
        return "month"

    @api.model
    def _base_domain(self, config_id=None):
        domain = [("shopify_config_id", "!=", False)]
        if config_id:
            domain.append(("shopify_config_id", "=", config_id))
        return domain

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from, date_to, config_id=None, granularity=None):
        # date_from/date_to arrivent en 'YYYY-MM-DD' depuis le JS. On les
        # convertit en date, puis les bornes utilisées dans les domaines sont
        # de vrais datetime (00:00:00 -> 23:59:59) : date_order est un champ
        # Datetime, et comparer un domaine à un simple objet date peut, selon
        # la configuration (timezone du serveur, driver), donner des
        # résultats incohérents voire faire échouer la requête. Les bornes
        # explicites en datetime évitent ce problème une fois pour toutes.
        date_from = fields.Date.from_string(date_from)
        date_to = fields.Date.from_string(date_to)
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        granularity = granularity if granularity in GRANULARITY_TRUNC else self._auto_granularity(
            date_from, date_to
        )

        nb_days = (date_to - date_from).days + 1
        prev_date_to = date_from - timedelta(days=1)
        prev_date_from = prev_date_to - timedelta(days=nb_days - 1)

        base_domain = self._base_domain(config_id)

        # Chaque bloc est isolé : si un calcul échoue (donnée corrompue,
        # champ manquant sur une vieille commande, etc.), il ne fait plus
        # planter tout le dashboard - on logge l'erreur et on renvoie une
        # valeur par défaut cohérente pour ce bloc uniquement.
        def safe(name, func, default):
            try:
                return func()
            except Exception:
                _logger.exception("Dashboard Shopify : échec du calcul '%s'", name)
                return default

        kpis_default = {
            key: {"value": 0, "delta": None}
            for key in ("revenue", "orders_count", "aov", "customers_count")
        }

        kpis = safe(
            "kpis",
            lambda: self._compute_kpis(base_domain, date_from, date_to, prev_date_from, prev_date_to),
            kpis_default,
        )
        timeseries = safe(
            "timeseries",
            lambda: self._compute_timeseries(base_domain, date_from, date_to, granularity),
            [],
        )
        top_products = safe(
            "top_products", lambda: self._compute_top_products(base_domain, date_from, date_to), []
        )
        revenue_by_shop = safe(
            "revenue_by_shop",
            lambda: self._compute_revenue_by_shop(base_domain, date_from, date_to),
            [],
        )
        status_breakdown = safe(
            "status_breakdown",
            lambda: self._compute_status_breakdown(base_domain, date_from, date_to),
            [],
        )
        recent_orders = safe(
            "recent_orders", lambda: self._compute_recent_orders(base_domain, date_from, date_to), []
        )
        shops = safe(
            "shops", lambda: self.env["shopify.config"].search_read([], ["id", "name"]), []
        )
        last_sync = safe("last_sync", lambda: self._compute_last_sync(config_id), None)
        reconciliation = safe(
            "reconciliation",
            lambda: self._compute_reconciliation(base_domain),
            {"total_all_time": 0, "confirmed_all_time": 0, "by_state": {}},
        )

        return {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "granularity": granularity,
            "currency_symbol": self.env.company.currency_id.symbol,
            "kpis": kpis,
            "timeseries": timeseries,
            "top_products": top_products,
            "revenue_by_shop": revenue_by_shop,
            "status_breakdown": status_breakdown,
            "recent_orders": recent_orders,
            "shops": shops,
            "last_sync": last_sync,
            "reconciliation": reconciliation,
        }

    @staticmethod
    def _day_bounds(date_from, date_to):
        """Renvoie (datetime_from, datetime_to_exclusive) pour bornes sûres
        sur un champ Datetime, quelle que soit la timezone du serveur."""
        dt_from = datetime.combine(date_from, time.min)
        dt_to_exclusive = datetime.combine(date_to + timedelta(days=1), time.min)
        return dt_from, dt_to_exclusive

    @api.model
    def _compute_reconciliation(self, base_domain):
        """Chiffres de référence, sans aucun filtre de date ni de statut :
        le total doit correspondre exactement au compteur 'Commandes
        (total)' du kanban Boutiques. Le détail par statut permet de voir
        précisément pourquoi le KPI 'Commandes confirmées' (period + state
        filtrés) est inférieur à ce total : commandes encore en devis,
        annulées, etc. Le cron ne fait que synchroniser les données
        Shopify telles quelles ; il ne force jamais une commande à passer
        confirmée si elle est annulée côté Shopify ou en échec de
        confirmation (voir _shopify_create_or_update_from_data)."""
        STATE_LABELS = {
            "draft": "En devis",
            "sent": "Devis envoyé",
            "sale": "Confirmée",
            "done": "Verrouillée",
            "cancel": "Annulée",
        }
        Sale = self.env["sale.order"]
        state_groups = Sale.read_group(base_domain, [], ["state"])
        by_state = {
            STATE_LABELS.get(g["state"], g["state"]): g["__count"] for g in state_groups
        }
        total_all_time = sum(by_state.values())
        confirmed_all_time = by_state.get("Confirmée", 0) + by_state.get("Verrouillée", 0)
        return {
            "total_all_time": total_all_time,
            "confirmed_all_time": confirmed_all_time,
            "by_state": by_state,
        }

    @api.model
    def _compute_last_sync(self, config_id=None):
        """Date de la synchro commandes la plus récente : c'est ce qui
        garantit que les chiffres du dashboard reflètent les dernières
        commandes importées depuis Shopify (le dashboard lui-même est
        toujours calculé en direct, sans cache)."""
        domain = [("last_sync_orders", "!=", False)]
        if config_id:
            domain.append(("id", "=", config_id))
        configs = self.env["shopify.config"].search(domain, order="last_sync_orders desc", limit=1)
        return fields.Datetime.to_string(configs.last_sync_orders) if configs else None

    # ------------------------------------------------------------------
    # KPI (avec comparaison à la période précédente de même durée)
    # ------------------------------------------------------------------
    @api.model
    def _kpi_snapshot(self, base_domain, date_from, date_to):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        orders = Sale.search(domain)
        revenue = sum(orders.mapped("amount_total"))
        orders_count = len(orders)
        customers_count = len(set(orders.mapped("partner_id").ids))
        aov = revenue / orders_count if orders_count else 0.0
        return revenue, orders_count, aov, customers_count

    @api.model
    def _compute_kpis(self, base_domain, date_from, date_to, prev_date_from, prev_date_to):
        revenue, orders_count, aov, customers = self._kpi_snapshot(base_domain, date_from, date_to)
        p_revenue, p_orders_count, p_aov, p_customers = self._kpi_snapshot(
            base_domain, prev_date_from, prev_date_to
        )

        def delta(curr, prev):
            if not prev:
                return None  # pas de base de comparaison valable
            return round((curr - prev) / prev * 100.0, 1)

        return {
            "revenue": {"value": revenue, "delta": delta(revenue, p_revenue)},
            "orders_count": {"value": orders_count, "delta": delta(orders_count, p_orders_count)},
            "aov": {"value": aov, "delta": delta(aov, p_aov)},
            "customers_count": {"value": customers, "delta": delta(customers, p_customers)},
        }

    # ------------------------------------------------------------------
    # Courbe temporelle CA + commandes
    # ------------------------------------------------------------------
    @api.model
    def _compute_timeseries(self, base_domain, date_from, date_to, granularity):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        groupby = GRANULARITY_TRUNC[granularity]
        groups = Sale.read_group(domain, ["amount_total:sum"], [groupby], orderby=groupby)
        result = []
        for group in groups:
            label = group.get(groupby)
            # read_group renvoie soit une string, soit un tuple (str, str) selon version
            if isinstance(label, (list, tuple)):
                label = label[0]
            result.append(
                {
                    "label": label,
                    "revenue": group.get("amount_total") or 0.0,
                    "orders_count": group.get("__count") or 0,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Top produits (quantité vendue / CA)
    # ------------------------------------------------------------------
    @api.model
    def _compute_top_products(self, base_domain, date_from, date_to, limit=8):
        Line = self.env["sale.order.line"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        order_domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        order_ids = self.env["sale.order"].search(order_domain).ids
        if not order_ids:
            return []
        line_domain = [
            ("order_id", "in", order_ids),
            ("display_type", "=", False),
            ("product_id", "!=", False),
        ]
        groups = Line.read_group(
            line_domain,
            ["price_subtotal:sum", "product_uom_qty:sum"],
            ["product_id"],
            orderby="price_subtotal desc",
            limit=limit,
        )
        result = []
        for group in groups:
            product = group.get("product_id")
            name = product[1] if product else "—"
            result.append(
                {
                    "name": name,
                    "revenue": group.get("price_subtotal") or 0.0,
                    "qty": group.get("product_uom_qty") or 0.0,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Répartition du CA par boutique (multi-store)
    # ------------------------------------------------------------------
    @api.model
    def _compute_revenue_by_shop(self, base_domain, date_from, date_to):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        groups = Sale.read_group(
            domain, ["amount_total:sum"], ["shopify_config_id"], orderby="amount_total desc"
        )
        result = []
        for group in groups:
            shop = group.get("shopify_config_id")
            name = shop[1] if shop else "—"
            result.append({"name": name, "revenue": group.get("amount_total") or 0.0})
        return result

    # ------------------------------------------------------------------
    # Répartition par statut financier Shopify (payé / en attente / etc.)
    # ------------------------------------------------------------------
    @api.model
    def _compute_status_breakdown(self, base_domain, date_from, date_to):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
        ]
        groups = Sale.read_group(
            domain, [], ["shopify_financial_status"], orderby="__count desc"
        )
        result = []
        for group in groups:
            status = group.get("shopify_financial_status") or "non défini"
            result.append({"status": status, "count": group.get("__count") or 0})
        return result

    # ------------------------------------------------------------------
    # Dernières commandes (pour la table du dashboard)
    # ------------------------------------------------------------------
    @api.model
    def _compute_recent_orders(self, base_domain, date_from, date_to, limit=8):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
        ]
        orders = Sale.search(domain, order="date_order desc", limit=limit)
        return [
            {
                "id": order.id,
                "name": order.name,
                "partner": order.partner_id.name or "—",
                "shop": order.shopify_config_id.name,
                "date": fields.Datetime.to_string(order.date_order) if order.date_order else "",
                "amount_total": order.amount_total,
                "state": order.state,
                "financial_status": order.shopify_financial_status or "",
            }
            for order in orders
        ]
