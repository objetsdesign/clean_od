/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Component, useState, useRef, onWillStart, onWillUnmount, useEffect } from "@odoo/owl";

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
        return `${sign}${delta}%`;
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
            const d = new Date(label);
            return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
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
        if (shop.error_count > 0) return { cls: "is-warn", label: `${shop.error_count} erreur(s)` };
        return { cls: "is-ok", label: "Opérationnelle" };
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

    renderTrendChart() {
        const canvas = this.canvasRefs.trend.el;
        if (!canvas) return;
        this.destroyChart("trend");
        const series = this.state.data.timeseries || [];
        const opts = this.baseOptions();
        opts.plugins.legend = { display: true, position: "top", align: "end", labels: { usePointStyle: true, boxWidth: 8, color: this.chartTheme.text } };
        opts.plugins.tooltip.callbacks = {
            label: (ctx) =>
                ctx.dataset.yAxisID === "y" ? `  CA : ${this.formatMoney(ctx.parsed.y)}` : `  ${ctx.parsed.y} commande(s)`,
        };
        opts.scales.y.ticks.callback = (v) => this.formatMoneyShort(v);
        opts.scales.y.beginAtZero = true;
        opts.scales.y1 = { position: "right", beginAtZero: true, grid: { display: false }, border: { display: false }, ticks: { precision: 0, color: this.chartTheme.text } };

        this.charts.trend = new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
                labels: series.map((p) => this.formatTimeLabel(p.label)),
                datasets: [
                    {
                        label: "Chiffre d'affaires",
                        data: series.map((p) => p.revenue),
                        borderColor: ACCENT,
                        backgroundColor: this.gradient(canvas, ACCENT),
                        borderWidth: 2.5,
                        tension: 0.3,
                        cubicInterpolationMode: "monotone",
                        fill: true,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        yAxisID: "y",
                    },
                    {
                        label: "Commandes",
                        data: series.map((p) => p.orders_count),
                        borderColor: ACCENT_2,
                        borderWidth: 2,
                        borderDash: [5, 4],
                        tension: 0.3,
                        cubicInterpolationMode: "monotone",
                        fill: false,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        yAxisID: "y1",
                    },
                ],
            },
            options: opts,
        });
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
