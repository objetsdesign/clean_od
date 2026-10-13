/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Component, markup, useState, useRef, onWillStart, onWillUnmount, useEffect } from "@odoo/owl";

const PERIOD_PRESETS = {
    "7": { label: "7 j", long: "7 derniers jours", days: 7 },
    "30": { label: "30 j", long: "30 derniers jours", days: 30 },
    "90": { label: "90 j", long: "90 derniers jours", days: 90 },
    "365": { label: "12 mois", long: "12 derniers mois", days: 365 },
    "all": { label: "Tout", long: "Depuis toujours", days: null },
};

const EPOCH_DATE = "2000-01-01";

// Palette catégorielle (CA par boutique) : teintes distinctes, lisibles
// sur fond clair comme sombre.
const SHOP_COLORS = ["#4F8A3C", "#5B5BD6", "#E5853B", "#D14B6A", "#2B9BA8", "#9A6BD8", "#C9A227", "#5F7387"];

const ACCENT = "#4F8A3C"; // vert Shopify assombri (contraste AA)
const ACCENT_2 = "#5B5BD6";

function toIsoDate(date) {
    return date.toISOString().slice(0, 10);
}

function cssVar(name, fallback) {
    const el = document.querySelector(".o_sd") || document.documentElement;
    const v = getComputedStyle(el).getPropertyValue(name).trim();
    return v || fallback;
}

export class ShopifyDashboard extends Component {
    static template = "shopify_odoo_connector.ShopifyDashboard";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.canvasRefs = {
            trend: useRef("trendCanvas"),
            amountDistribution: useRef("amountDistributionCanvas"),
            shop: useRef("shopCanvas"),
            products: useRef("productsCanvas"),
        };
        this.charts = {};

        this.state = useState({
            loading: true,
            refreshing: false,
            error: null,
            period: "30",
            configId: null,
            data: null,
            syncing: {},
            trendMetric: "revenue",
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.fetchData();
        });

        useEffect(
            () => {
                if (!this.state.loading && this.state.data) {
                    this.renderCharts();
                }
            },
            () => [this.state.loading, this.state.data]
        );

        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => chart && chart.destroy());
        });
    }

    // ------------------------------------------------------------------
    // Données
    // ------------------------------------------------------------------
    getRange() {
        const preset = PERIOD_PRESETS[this.state.period];
        const dateTo = new Date();
        if (preset.days === null) {
            return { date_from: EPOCH_DATE, date_to: toIsoDate(dateTo) };
        }
        const dateFrom = new Date();
        dateFrom.setDate(dateFrom.getDate() - (preset.days - 1));
        return { date_from: toIsoDate(dateFrom), date_to: toIsoDate(dateTo) };
    }

    async fetchData({ soft = false } = {}) {
        // « soft » : on garde l'écran affiché pendant le rechargement
        // (pas de squelette qui clignote quand on change de filtre).
        if (soft && this.state.data) {
            this.state.refreshing = true;
        } else {
            this.state.loading = true;
        }
        this.state.error = null;
        const { date_from, date_to } = this.getRange();
        try {
            const data = await rpc("/shopify_connector/dashboard_data", {
                date_from,
                date_to,
                config_id: this.state.configId || null,
            });
            if (data && data.error) {
                this.state.error = data.error;
            } else {
                this.state.data = data;
            }
        } catch {
            this.state.error = "Impossible de charger les statistiques.";
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    async setPeriod(value) {
        if (this.state.period === value) return;
        this.state.period = value;
        await this.fetchData({ soft: true });
    }

    async onShopChange(ev) {
        const value = ev.target.value;
        this.state.configId = value ? parseInt(value, 10) : null;
        await this.fetchData({ soft: true });
    }

    async onRefresh() {
        await this.fetchData({ soft: true });
        this.notification.add("Tableau de bord actualisé.", { type: "success" });
    }

    async syncShop(shop) {
        if (this.state.syncing[shop.id]) return;
        this.state.syncing[shop.id] = true;
        try {
            const result = await this.orm.call("shopify.config", "action_sync_all_now", [[shop.id]]);
            if (result && result.type) {
                await this.action.doAction(result);
            } else {
                this.notification.add(`Synchronisation de « ${shop.name} » terminée.`, { type: "success" });
            }
            await this.fetchData({ soft: true });
        } catch (e) {
            this.notification.add(`La synchronisation de « ${shop.name} » a échoué.`, { type: "danger" });
            throw e;
        } finally {
            this.state.syncing[shop.id] = false;
        }
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------
    onOpenShops() {
        this.action.doAction("shopify_odoo_connector.action_shopify_dashboard");
    }

    onOpenQuotations() {
        this.action.doAction("shopify_odoo_connector.action_shopify_quotations");
    }

    onOpenSyncLog() {
        this.action.doAction("shopify_odoo_connector.action_shopify_sync_log");
    }

    openShop(shopId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "shopify.config",
            res_id: shopId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openShopErrors(shopId) {
        const action = await this.orm.call("shopify.config", "action_view_sync_errors", [[shopId]]);
        await this.action.doAction(action);
    }

    // Ouvre une liste filtrée (cartes « À traiter », barres de statut).
    openDomain(model, domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Shopify",
            res_model: model,
            domain: domain || [],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    // Couleur d'un statut (paiement, expédition, livraison).
    statusTone(key) {
        const tones = {
            paid: "green", fulfilled: "green", delivered: "green", picked_up: "green",
            pending: "orange", authorized: "orange", partially_paid: "orange", unfulfilled: "orange",
            partial: "orange", label_purchased: "orange", label_printed: "orange", attempted_delivery: "orange",
            shipped: "blue", confirmed: "blue", in_transit: "blue", carrier_picked_up: "blue",
            out_for_delivery: "blue", ready_for_pickup: "blue",
            refunded: "red", voided: "red", partially_refunded: "red", failure: "red",
            restocked: "gray", other: "gray",
        };
        return tones[key] || "gray";
    }

    percent(part, total) {
        if (!total) return "";
        const p = (part / total) * 100;
        return `${p < 10 ? p.toFixed(1).replace(".", ",") : Math.round(p)} %`;
    }

    formatDay(iso) {
        if (!iso) return "";
        return new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
    }

    get bestPoint() {
        const series = (this.state.data && this.state.data.timeseries) || [];
        let best = null;
        for (const p of series) {
            if (p.revenue > 0 && (!best || p.revenue > best.revenue)) best = p;
        }
        return best;
    }

    get topProductsTotal() {
        const products = (this.state.data && this.state.data.top_products) || [];
        return products.reduce((a, p) => a + (p.revenue || 0), 0);
    }

    shopRevenue(name) {
        const row = ((this.state.data && this.state.data.revenue_by_shop) || []).find((r) => r.name === name);
        return row ? row.revenue : 0;
    }

    // Phrase de résumé en haut de page, en français simple.
    get summaryText() {
        const d = this.state.data;
        if (!d) return "";
        const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
        const k = d.kpis;
        const n = k.orders_count.value;
        if (!n) {
            return markup(`Aucune commande sur la période. ${this.todoSentence(esc)}`);
        }
        let text = `<strong>${esc(n)} commande${n > 1 ? "s" : ""}</strong> pour <strong>${esc(this.formatMoney(k.revenue.value))}</strong>` +
            `, soit <strong>${esc(this.formatMoney(k.aov.value))}</strong> en moyenne par commande.`;
        if (k.revenue.delta !== null && k.revenue.delta !== undefined) {
            const up = k.revenue.delta >= 0;
            text += ` Le chiffre d'affaires est <strong class="${up ? "o_sd_txt_up" : "o_sd_txt_down"}">${up ? "en hausse" : "en baisse"} de ${esc(String(Math.abs(k.revenue.delta)).replace(".", ","))} %</strong> par rapport à la période précédente.`;
        }
        text += " " + this.todoSentence(esc);
        return markup(text);
    }

    todoSentence(esc) {
        const todo = (this.state.data && this.state.data.todo) || [];
        const ship = todo.find((t) => t.key === "to_ship");
        const issues = todo.filter((t) => t.count && t.tone === "red");
        const parts = [];
        if (ship && ship.count) parts.push(`commandes à expédier : ${esc(ship.count)}`);
        for (const t of issues) parts.push(`${esc(t.label.toLowerCase())} : ${esc(t.count)}`);
        if (!parts.length) return "Rien d'urgent à traiter. 👍";
        return `À traiter : <strong>${parts.join(", ")}</strong> (voir section 2).`;
    }

    openOrder(orderId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------
    // Formatage (utilisé dans le template)
    // ------------------------------------------------------------------
    formatMoney(value) {
        const symbol = (this.state.data && this.state.data.currency_symbol) || "€";
        return `${formatFloat(value || 0, { digits: [16, 2] })} ${symbol}`;
    }

    formatMoneyShort(value) {
        const symbol = (this.state.data && this.state.data.currency_symbol) || "€";
        const v = value || 0;
        if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1).replace(".", ",")} M${symbol}`;
        if (Math.abs(v) >= 1e4) return `${Math.round(v / 1e3)} k${symbol}`;
        return `${Math.round(v)} ${symbol}`;
    }

    formatDelta(delta) {
        if (delta === null || delta === undefined) return null;
        const sign = delta > 0 ? "+" : "";
        return `${sign}${String(delta).replace(".", ",")} %`;
    }

    deltaClass(delta) {
        if (delta === null || delta === undefined) return "is-new";
        return delta >= 0 ? "is-up" : "is-down";
    }

    deltaIcon(delta) {
        if (delta === null || delta === undefined) return "fa-star";
        return delta >= 0 ? "fa-arrow-up" : "fa-arrow-down";
    }

    // Dates serveur (UTC « YYYY-MM-DD HH:MM:SS ») -> « il y a 5 min »
    timeAgo(value) {
        if (!value) return "jamais";
        const d = new Date(value.replace(" ", "T") + "Z");
        const s = Math.round((Date.now() - d.getTime()) / 1000);
        if (s < 60) return "à l'instant";
        if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
        if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
        if (s < 86400 * 30) return `il y a ${Math.floor(s / 86400)} j`;
        return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
    }

    formatOrderDate(value) {
        if (!value) return "";
        const d = new Date(value.replace(" ", "T") + "Z");
        return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" }) +
            " · " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    }

    formatTimeLabel(label) {
        if (!label) return "";
        if (/^\d{4}-\d{2}-\d{2}/.test(label)) {
            const d = new Date(label.slice(0, 10) + "T12:00:00");
            const g = this.state.data && this.state.data.granularity;
            if (g === "month") {
                return d.toLocaleDateString("fr-FR", { month: "short", year: "numeric" });
            }
            return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
        }
        return label;
    }

    initials(name) {
        return (name || "?")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((w) => w[0].toUpperCase())
            .join("");
    }

    shopHealth(shop) {
        if (shop.state !== "connected") return { cls: "is-off", label: shop.state === "error" ? "Erreur" : "Non connectée" };
        if (shop.error_count > 0) return { cls: "is-warn", label: "Connectée · des erreurs sont à vérifier" };
        return { cls: "is-ok", label: "Connectée · tout fonctionne" };
    }

    activityIcon(item) {
        if (item.state === "error") return "fa-exclamation";
        if (item.is_delete) return "fa-trash-o";
        return item.direction === "in" ? "fa-arrow-down" : "fa-arrow-up";
    }

    activityClass(item) {
        if (item.state === "error") return "is-error";
        if (item.is_delete) return "is-delete";
        return item.direction === "in" ? "is-in" : "is-out";
    }

    get periodOptions() {
        return Object.entries(PERIOD_PRESETS).map(([value, p]) => ({ value, label: p.label, long: p.long }));
    }

    get periodLabel() {
        return PERIOD_PRESETS[this.state.period].long;
    }

    get greeting() {
        const h = new Date().getHours();
        return h < 18 ? "Bonjour" : "Bonsoir";
    }

    // ------------------------------------------------------------------
    // Graphiques
    // ------------------------------------------------------------------
    get chartTheme() {
        return {
            text: cssVar("--sd-muted", "#6B7280"),
            grid: cssVar("--sd-border", "rgba(0,0,0,0.06)"),
            surface: cssVar("--sd-surface", "#fff"),
        };
    }

    baseOptions() {
        const t = this.chartTheme;
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 450 },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(17,24,39,0.92)",
                    padding: 10,
                    cornerRadius: 8,
                    titleFont: { weight: "600" },
                    boxPadding: 4,
                },
            },
            scales: {
                x: { grid: { display: false }, border: { display: false }, ticks: { color: t.text, maxRotation: 0, autoSkipPadding: 16 } },
                y: { grid: { color: t.grid }, border: { display: false }, ticks: { color: t.text } },
            },
        };
    }

    renderCharts() {
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        this.renderTrendChart();
        this.renderAmountDistributionChart();
        this.renderShopChart();
        this.renderProductsChart();
    }

    destroyChart(key) {
        if (this.charts[key]) {
            this.charts[key].destroy();
            this.charts[key] = null;
        }
    }

    gradient(canvas, color) {
        const ctx = canvas.getContext("2d");
        const g = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 280);
        g.addColorStop(0, color + "40");
        g.addColorStop(1, color + "00");
        return g;
    }

    setTrendMetric(metric) {
        if (this.state.trendMetric === metric) return;
        this.state.trendMetric = metric;
        this.renderTrendChart();
    }

    get trendTotal() {
        const series = (this.state.data && this.state.data.timeseries) || [];
        if (this.state.trendMetric === "orders") {
            const n = series.reduce((a, p) => a + (p.orders_count || 0), 0);
            return `${n} commande${n > 1 ? "s" : ""}`;
        }
        return this.formatMoney(series.reduce((a, p) => a + (p.revenue || 0), 0));
    }

    // Une seule mesure à la fois (une seule échelle) : euros OU commandes.
    // Deux échelles sur le même graphique rendaient la lecture trompeuse.
    renderTrendChart() {
        const canvas = this.canvasRefs.trend.el;
        if (!canvas) return;
        this.destroyChart("trend");
        const series = this.state.data.timeseries || [];
        const isOrders = this.state.trendMetric === "orders";
        const color = isOrders ? ACCENT_2 : ACCENT;
        const opts = this.baseOptions();
        opts.plugins.tooltip.callbacks = {
            title: (items) => (items[0] ? this.formatTimeLabel(series[items[0].dataIndex].label) : ""),
            label: (ctx) =>
                isOrders ? `  ${ctx.parsed.y} commande${ctx.parsed.y > 1 ? "s" : ""}` : `  ${this.formatMoney(ctx.parsed.y)}`,
        };
        opts.scales.y.beginAtZero = true;
        opts.scales.y.ticks.maxTicksLimit = 5;
        if (isOrders) {
            opts.scales.y.ticks.precision = 0;
        } else {
            opts.scales.y.ticks.callback = (v) => this.formatMoneyShort(v);
        }
        opts.scales.x.ticks.maxTicksLimit = 8;
        const dataset = isOrders
            ? {
                  type: "bar",
                  label: "Commandes",
                  data: series.map((p) => p.orders_count),
                  backgroundColor: color,
                  hoverBackgroundColor: color,
                  borderRadius: 4,
                  borderSkipped: "start",
                  maxBarThickness: 22,
                  categoryPercentage: 0.8,
              }
            : {
                  type: "line",
                  label: "Chiffre d'affaires",
                  data: series.map((p) => p.revenue),
                  borderColor: color,
                  backgroundColor: this.gradient(canvas, color),
                  borderWidth: 2,
                  tension: 0.25,
                  cubicInterpolationMode: "monotone",
                  fill: true,
                  pointRadius: series.length <= 14 ? 3 : 0,
                  pointBackgroundColor: color,
                  pointBorderColor: this.chartTheme.surface,
                  pointBorderWidth: 2,
                  pointHoverRadius: 5,
                  pointHoverBorderWidth: 2,
                  pointHoverBorderColor: this.chartTheme.surface,
              };
        this.charts.trend = new Chart(canvas.getContext("2d"), {
            type: isOrders ? "bar" : "line",
            data: { labels: series.map((p) => this.formatTimeLabel(p.label)), datasets: [dataset] },
            options: opts,
        });
    }

    // Mini-courbe des cartes KPI (SVG, sans librairie).
    sparkPoints(kind) {
        const series = (this.state.data && this.state.data.timeseries) || [];
        let values;
        if (kind === "revenue") {
            values = series.map((p) => p.revenue || 0);
        } else if (kind === "orders") {
            values = series.map((p) => p.orders_count || 0);
        } else if (kind === "aov") {
            values = series.filter((p) => p.orders_count).map((p) => p.revenue / p.orders_count);
        } else {
            return "";
        }
        if (values.length < 2) return "";
        const max = Math.max(...values);
        const min = Math.min(...values, 0);
        const span = max - min || 1;
        const w = 120, h = 34, pad = 2;
        return values
            .map((v, i) => {
                const x = (i / (values.length - 1)) * w;
                const y = pad + (h - 2 * pad) * (1 - (v - min) / span);
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
    }

    sparkArea(kind) {
        const pts = this.sparkPoints(kind);
        return pts ? `0,34 ${pts} 120,34` : "";
    }

    renderAmountDistributionChart() {
        const canvas = this.canvasRefs.amountDistribution.el;
        if (!canvas) return;
        this.destroyChart("amountDistribution");
        const rows = this.state.data.amount_distribution || [];
        if (!rows.length) return;
        const opts = this.baseOptions();
        opts.plugins.tooltip.callbacks = { label: (ctx) => `  ${ctx.parsed.y} commande(s)` };
        opts.scales.y.beginAtZero = true;
        opts.scales.y.ticks.precision = 0;
        this.charts.amountDistribution = new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ data: rows.map((r) => r.count), backgroundColor: ACCENT_2, borderRadius: 6, maxBarThickness: 36 }],
            },
            options: opts,
        });
    }

    renderShopChart() {
        const canvas = this.canvasRefs.shop.el;
        if (!canvas) return;
        this.destroyChart("shop");
        const rows = this.state.data.revenue_by_shop || [];
        if (!rows.length) return;
        this.charts.shop = new Chart(canvas.getContext("2d"), {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.name),
                datasets: [{
                    data: rows.map((r) => r.revenue),
                    backgroundColor: rows.map((_, i) => SHOP_COLORS[i % SHOP_COLORS.length]),
                    borderWidth: 3,
                    borderColor: this.chartTheme.surface,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "72%",
                plugins: {
                    legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 14, color: this.chartTheme.text } },
                    tooltip: { backgroundColor: "rgba(17,24,39,0.92)", padding: 10, cornerRadius: 8, callbacks: { label: (ctx) => ` ${ctx.label} : ${this.formatMoney(ctx.parsed)}` } },
                },
            },
        });
    }

    renderProductsChart() {
        // Top produits : rendu en liste HTML (barres CSS), plus lisible que
        // des libellés tronqués dans un canvas. Rien à dessiner ici.
        this.destroyChart("products");
    }

    get maxTopProductRevenue() {
        const products = (this.state.data && this.state.data.top_products) || [];
        return Math.max(1, ...products.map((p) => p.revenue));
    }

    shopColor(index) {
        return SHOP_COLORS[index % SHOP_COLORS.length];
    }
}

registry.category("actions").add("shopify_sales_dashboard", ShopifyDashboard);
