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

    @staticmethod
    def _group_count(group):
        """Lit le nombre d'enregistrements d'un groupe issu de read_group.

        On a constaté sur certains builds Odoo que la clé interne
        '__count' n'est pas toujours fiable pour lire la valeur après
        coup (le CA agrégé est correct mais le nombre de commandes
        remonte à 0). Pour ne plus en dépendre, on demande explicitement
        l'agrégat 'id:count' dans les 'fields' de read_group : Odoo range
        alors le résultat sous la clé 'id'. On garde '__count' en repli
        pour rester compatible si jamais 'id' n'est pas présent."""
        return group.get("id") if group.get("id") is not None else (group.get("__count") or 0)

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
        amount_distribution = safe(
            "amount_distribution",
            lambda: self._compute_amount_distribution(base_domain, date_from, date_to),
            [],
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

        todo = safe("todo", lambda: self._compute_todo(base_domain, config_id), [])
        order_status = safe(
            "order_status",
            lambda: self._compute_order_status(base_domain, date_from, date_to),
            {"payment": [], "fulfillment": [], "total": 0},
        )
        sync_health = safe("sync_health", lambda: self._compute_sync_health(config_id), [])
        activity = safe("activity", lambda: self._compute_activity(config_id), [])

        return {
            "todo": todo,
            "order_status": order_status,
            "sync_health": sync_health,
            "activity": activity,
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "granularity": granularity,
            "currency_symbol": self.env.company.currency_id.symbol,
            "kpis": kpis,
            "timeseries": timeseries,
            "top_products": top_products,
            "amount_distribution": amount_distribution,
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
        state_groups = Sale.read_group(base_domain, ["id:count"], ["state"])
        by_state = {
            STATE_LABELS.get(g["state"], g["state"]): self._group_count(g) for g in state_groups
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
        """Le nombre de commandes ET le nombre de clients affichés sont les
        TOTAUX de la période, tous statuts confondus (devis compris) : ce
        sont les chiffres que les utilisateurs s'attendent à voir en gros
        sur ces KPI, cohérents avec les compteurs 'Clients'/'Commandes
        (total)' affichés ailleurs (kanban Boutiques). Le chiffre
        d'affaires et le panier moyen restent en revanche calculés
        uniquement sur les ventes réellement confirmées (state in
        SALE_STATES), sans quoi ces deux métriques n'auraient plus de sens
        commercial (un devis n'est pas une vente réalisée)."""
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        period_domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
        ]
        all_orders = Sale.search(period_domain)
        orders_count = len(all_orders)
        customers_count = len(set(all_orders.mapped("partner_id").ids))

        confirmed_orders = all_orders.filtered(lambda o: o.state in SALE_STATES)
        revenue = sum(confirmed_orders.mapped("amount_total"))
        aov = revenue / len(confirmed_orders) if confirmed_orders else 0.0
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
            "revenue": {"value": revenue, "delta": delta(revenue, p_revenue), "previous": p_revenue},
            "orders_count": {"value": orders_count, "delta": delta(orders_count, p_orders_count), "previous": p_orders_count},
            "aov": {"value": aov, "delta": delta(aov, p_aov), "previous": p_aov},
            "customers_count": {"value": customers, "delta": delta(customers, p_customers), "previous": p_customers},
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
        groups = Sale.read_group(
            domain, ["amount_total:sum", "id:count"], [groupby], orderby=groupby
        )
        # Clé ISO du début de chaque période (fournie par read_group dans
        # « __range »), pour pouvoir compléter les périodes SANS vente par
        # des zéros : sinon la courbe relie directement le 17 au 23 sept.
        # comme s'il y avait eu des ventes entre les deux.
        by_start, fallback = {}, []
        for group in groups:
            label = group.get(groupby)
            if isinstance(label, (list, tuple)):
                label = label[0]
            point = {
                "label": label,
                "revenue": group.get("amount_total") or 0.0,
                "orders_count": self._group_count(group),
            }
            start = ((group.get("__range") or {}).get(groupby) or {}).get("from")
            if start:
                by_start[self._range_start_local_day(start)] = point
            else:
                fallback.append(point)
        if fallback or not by_start:
            return fallback or []
        return self._fill_timeseries(by_start, date_from, date_to, granularity)

    @api.model
    def _range_start_local_day(self, start):
        """Début de période renvoyé par read_group (heure UTC pour un champ
        Datetime) -> jour local de l'utilisateur, au format AAAA-MM-JJ."""
        start = str(start)
        if len(start) <= 10:
            return start[:10]
        tz_name = self.env.context.get("tz") or self.env.user.tz
        try:
            import pytz

            utc_dt = pytz.utc.localize(fields.Datetime.from_string(start))
            return utc_dt.astimezone(pytz.timezone(tz_name)).date().isoformat() if tz_name else start[:10]
        except Exception:  # noqa: BLE001
            return start[:10]

    @api.model
    def _fill_timeseries(self, by_start, date_from, date_to, granularity):
        def bucket_start(day):
            if granularity == "week":
                return day - timedelta(days=day.weekday())
            if granularity == "month":
                return day.replace(day=1)
            return day

        def next_bucket(day):
            if granularity == "week":
                return day + timedelta(days=7)
            if granularity == "month":
                return (day.replace(day=28) + timedelta(days=4)).replace(day=1)
            return day + timedelta(days=1)

        first_sale = min(fields.Date.to_date(k) for k in by_start)
        # Période « Tout » (depuis 2000) : on démarre à la 1re vente.
        current = bucket_start(max(fields.Date.to_date(date_from), first_sale)
                               if (fields.Date.to_date(date_to) - fields.Date.to_date(date_from)).days > 400
                               else fields.Date.to_date(date_from))
        end = fields.Date.to_date(date_to)
        result = []
        while current <= end and len(result) < 1000:
            key = current.isoformat()
            point = by_start.get(key) or {"revenue": 0.0, "orders_count": 0}
            result.append(
                {"label": key, "revenue": point["revenue"], "orders_count": point["orders_count"]}
            )
            current = next_bucket(current)
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
    # Répartition des commandes par tranche de montant
    # ------------------------------------------------------------------
    @api.model
    def _compute_amount_distribution(self, base_domain, date_from, date_to, bins=8):
        """Nombre de commandes par tranche de montant.

        Utile en complément de la courbe temporelle : quand beaucoup de
        commandes partagent exactement la même date_order (import en
        masse d'une boutique de test, par exemple), la courbe dans le
        temps n'a qu'un seul point à afficher. La répartition par montant,
        elle, reste parlante puisque les montants des commandes varient
        entre eux même si leur date ne varie pas."""
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        amounts = self.env["sale.order"].search(domain).mapped("amount_total")
        if not amounts:
            return []

        min_amount, max_amount = min(amounts), max(amounts)
        if min_amount == max_amount:
            return [{"label": f"{min_amount:.0f} €", "count": len(amounts)}]

        bin_size = (max_amount - min_amount) / bins
        buckets = [0] * bins
        for amount in amounts:
            idx = int((amount - min_amount) / bin_size)
            if idx >= bins:
                idx = bins - 1
            buckets[idx] += 1

        result = []
        for i, count in enumerate(buckets):
            low = min_amount + i * bin_size
            high = low + bin_size
            result.append({"label": f"{low:.0f}–{high:.0f} €", "count": count})
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
            domain, ["id:count"], ["shopify_financial_status"], orderby="id desc"
        )
        result = []
        for group in groups:
            status = group.get("shopify_financial_status") or "non défini"
            result.append({"status": status, "count": self._group_count(group)})
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
                "state_label": self._selection_label(order, "state"),
                "payment_key": order.shopify_payment_state or "",
                "payment_label": self._selection_label(order, "shopify_payment_state"),
                "fulfillment_key": order.shopify_fulfillment_status or "",
                "fulfillment_label": self._selection_label(order, "shopify_fulfillment_status"),
                "delivery_key": order.shopify_delivery_status or "",
                "delivery_label": self._selection_label(order, "shopify_delivery_status"),
            }
            for order in orders
        ]

    @api.model
    def _selection_label(self, record, field_name):
        value = record[field_name]
        if not value:
            return ""
        return dict(record._fields[field_name]._description_selection(self.env)).get(value, value)

    # ------------------------------------------------------------------
    # « À traiter maintenant » : tout ce qui attend une action, quelle
    # que soit la période choisie (une commande à expédier reste à
    # expédier même si elle date du mois dernier).
    # ------------------------------------------------------------------
    @api.model
    def _compute_todo(self, base_domain, config_id=None):
        Sale = self.env["sale.order"]
        active_orders = base_domain + [("state", "in", SALE_STATES)]

        def order_item(key, label, hint, icon, tone, domain):
            orders = Sale.search(domain)
            return {
                "key": key, "label": label, "hint": hint, "icon": icon, "tone": tone,
                "count": len(orders), "amount": sum(orders.mapped("amount_total")),
                "model": "sale.order", "domain": domain,
            }

        items = [
            order_item(
                "to_ship", "Commandes à expédier",
                "Confirmées et payées ou non, mais pas encore expédiées dans Shopify.",
                "fa-truck", "orange",
                active_orders + [("shopify_fulfillment_status", "in", ("unfulfilled", "partial")),
                                 ("shopify_cancelled_at", "=", False)],
            ),
            order_item(
                "payment_pending", "Paiements en attente",
                "Commandes dont le paiement Shopify n'est pas encore encaissé.",
                "fa-hourglass-half", "orange",
                active_orders + [("shopify_payment_state", "in", ("pending", "authorized", "partially_paid"))],
            ),
            order_item(
                "delivery_issue", "Problèmes de livraison",
                "Livraison en échec ou tentative de livraison sans succès.",
                "fa-exclamation-circle", "red",
                active_orders + [("shopify_delivery_status", "in", ("failure", "attempted_delivery"))],
            ),
            order_item(
                "to_invoice", "Commandes à facturer",
                "Commandes confirmées pour lesquelles aucune facture n'a encore été créée.",
                "fa-file-text-o", "blue",
                active_orders + [("invoice_status", "=", "to invoice")],
            ),
            order_item(
                "quotations", "Devis non confirmés",
                "Commandes Shopify restées en devis : elles ne comptent pas dans le chiffre d'affaires.",
                "fa-pencil-square-o", "gray",
                base_domain + [("state", "in", ("draft", "sent"))],
            ),
        ]

        # Produits liés à Shopify et en rupture de stock
        Template = self.env["product.template"]
        product_domain = [("shopify_link_ids", "!=", False), ("is_storable", "=", True), ("qty_available", "<=", 0)]
        if config_id:
            product_domain.append(("shopify_link_ids.config_id", "=", config_id))
        try:
            out_ids = Template.search(product_domain).ids
        except Exception:  # noqa: BLE001
            out_ids = []
        items.append({
            "key": "out_of_stock", "label": "Produits en rupture",
            "hint": "Produits publiés sur Shopify avec un stock Odoo à 0 : ils ne peuvent plus être vendus.",
            "icon": "fa-cubes", "tone": "red", "count": len(out_ids), "amount": 0,
            "model": "product.template", "domain": [("id", "in", out_ids)],
        })

        # Erreurs de synchronisation (7 derniers jours)
        log_domain = [("state", "=", "error"),
                      ("create_date", ">=", fields.Datetime.now() - timedelta(days=7))]
        if config_id:
            log_domain.append(("config_id", "=", config_id))
        items.append({
            "key": "sync_errors", "label": "Erreurs de synchronisation",
            "hint": "Envois ou imports Shopify en erreur ces 7 derniers jours (voir le journal).",
            "icon": "fa-plug", "tone": "red",
            "count": self.env["shopify.sync.log"].search_count(log_domain), "amount": 0,
            "model": "shopify.sync.log", "domain": log_domain,
        })
        return items

    # ------------------------------------------------------------------
    # « Où en sont les commandes ? » : paiement et expédition des
    # commandes confirmées de la période.
    # ------------------------------------------------------------------
    @api.model
    def _compute_order_status(self, base_domain, date_from, date_to):
        Sale = self.env["sale.order"]
        dt_from, dt_to_exclusive = self._day_bounds(date_from, date_to)
        domain = base_domain + [
            ("date_order", ">=", dt_from),
            ("date_order", "<", dt_to_exclusive),
            ("state", "in", SALE_STATES),
        ]
        total = Sale.search_count(domain)

        def breakdown(field_name, empty_label):
            labels = dict(Sale._fields[field_name]._description_selection(self.env))
            rows = []
            for group in Sale.read_group(domain, ["id:count"], [field_name], lazy=False):
                key = group.get(field_name) or ""
                rows.append({
                    "key": key,
                    "label": labels.get(key, empty_label) if key else empty_label,
                    "count": group.get("__count") or self._group_count(group),
                    "domain": domain + [(field_name, "=", key or False)],
                })
            rows.sort(key=lambda r: -r["count"])
            return rows

        return {
            "total": total,
            "payment": breakdown("shopify_payment_state", "Non renseigné"),
            "fulfillment": breakdown("shopify_fulfillment_status", "Non renseigné"),
        }

    # ------------------------------------------------------------------
    # Santé de la synchronisation (v9.7) : une ligne par boutique
    # ------------------------------------------------------------------
    @api.model
    def _compute_sync_health(self, config_id=None):
        domain = [("id", "=", config_id)] if config_id else []
        result = []
        for config in self.env["shopify.config"].search(domain, order="name"):
            result.append({
                "id": config.id,
                "name": config.name,
                "shop_url": config.shop_url or "",
                "state": config.state,
                "product_count": config.product_count,
                "order_count": config.order_count,
                "error_count": config.sync_error_count,
                "webhook_pending": config.webhook_pending_count,
                "last_sync_products": fields.Datetime.to_string(config.last_sync_products) if config.last_sync_products else None,
                "last_sync_orders": fields.Datetime.to_string(config.last_sync_orders) if config.last_sync_orders else None,
            })
        return result

    @api.model
    def _compute_activity(self, config_id=None, limit=12):
        """Dernières opérations de synchronisation (imports, envois,
        suppressions, erreurs) pour le fil d'activité du dashboard."""
        domain = [("config_id", "=", config_id)] if config_id else []
        logs = self.env["shopify.sync.log"].search(domain, order="id desc", limit=limit)
        return [
            {
                "id": log.id,
                "date": fields.Datetime.to_string(log.create_date),
                "direction": log.direction,
                "state": log.state,
                "shop": log.config_id.name,
                "object_type": log.shopify_object_type or "",
                "message": (log.message or "").strip()[:180],
                "is_delete": "supprim" in (log.message or "").lower(),
            }
            for log in logs
        ]
