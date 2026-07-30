/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";

const PERIOD_PRESETS = {
    "7": { label: "7 derniers jours", days: 7 },
    "30": { label: "30 derniers jours", days: 30 },
    "90": { label: "90 derniers jours", days: 90 },
    "365": { label: "12 derniers mois", days: 365 },
    "all": { label: "Depuis toujours", days: null },
};

// Odoo n'existant pas avant ça, largement suffisant comme borne basse
// pour un filtre "Depuis toujours" sans avoir à interroger la base.
const EPOCH_DATE = "2000-01-01";

const SHOP_COLORS = ["#95BF47", "#5C6AC4", "#F49342", "#DE3618", "#47C1BF", "#9C6ADE", "#006FBB", "#EEC200"];

function toIsoDate(date) {
    return date.toISOString().slice(0, 10);
}

export class ShopifyDashboard extends Component {
    static template = "shopify_odoo_connector.ShopifyDashboard";

    setup() {
        this.action = useService("action");
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
            error: null,
            period: "30",
            configId: null,
            data: null,
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
    // Data fetching
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

    async fetchData() {
        this.state.loading = true;
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
        } catch (err) {
            this.state.error = "Impossible de charger les statistiques.";
        } finally {
            this.state.loading = false;
        }
    }

    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        await this.fetchData();
    }

    async onShopChange(ev) {
        const value = ev.target.value;
        this.state.configId = value ? parseInt(value, 10) : null;
        await this.fetchData();
    }

    async onRefresh() {
        await this.fetchData();
        this.notification.add("Statistiques actualisées.", { type: "success" });
    }

    onOpenShops() {
        this.action.doAction("shopify_odoo_connector.action_shopify_dashboard");
    }

    onOpenQuotations() {
        this.action.doAction("shopify_odoo_connector.action_shopify_quotations");
    }

    // ------------------------------------------------------------------
    // Formatting helpers (utilisés dans le template)
    // ------------------------------------------------------------------
    formatMoney(value) {
        const symbol = (this.state.data && this.state.data.currency_symbol) || "€";
        return `${formatFloat(value || 0, { digits: [16, 2] })} ${symbol}`;
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

    formatTimeLabel(label) {
        if (!label) return "";
        // "2026-07-01" ou "2026-W30" ou "July 2026" selon granularité
        if (/^\d{4}-\d{2}-\d{2}/.test(label)) {
            const d = new Date(label);
            return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
        }
        return label;
    }

    get periodOptions() {
        return Object.entries(PERIOD_PRESETS).map(([value, { label }]) => ({ value, label }));
    }

    get maxTopProductRevenue() {
        const products = (this.state.data && this.state.data.top_products) || [];
        return Math.max(1, ...products.map((p) => p.revenue));
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
    // Charts
    // ------------------------------------------------------------------
    renderCharts() {
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

    renderTrendChart() {
        const canvas = this.canvasRefs.trend.el;
        if (!canvas) return;
        this.destroyChart("trend");
        const series = this.state.data.timeseries;
        const labels = series.map((p) => this.formatTimeLabel(p.label));
        const revenueData = series.map((p) => p.revenue);
        const ordersData = series.map((p) => p.orders_count);

        this.charts.trend = new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        type: "line",
                        label: "Chiffre d'affaires",
                        data: revenueData,
                        borderColor: "#95BF47",
                        backgroundColor: "rgba(149, 191, 71, 0.12)",
                        borderWidth: 2.5,
                        tension: 0.35,
                        fill: true,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        yAxisID: "y",
                        order: 1,
                    },
                    {
                        type: "line",
                        label: "Commandes",
                        data: ordersData,
                        borderColor: "#5C6AC4",
                        backgroundColor: "rgba(92, 106, 196, 0.12)",
                        borderWidth: 2.5,
                        tension: 0.35,
                        fill: false,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        yAxisID: "y1",
                        order: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "top", labels: { usePointStyle: true, boxWidth: 8 } },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                if (ctx.dataset.label === "Chiffre d'affaires") {
                                    return `  ${this.formatMoney(ctx.parsed.y)}`;
                                }
                                return `  ${ctx.parsed.y} commande(s)`;
                            },
                        },
                    },
                },
                scales: {
                    y: {
                        position: "left",
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { callback: (v) => this.formatMoney(v) },
                    },
                    y1: {
                        position: "right",
                        grid: { display: false },
                        ticks: { precision: 0 },
                    },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    renderAmountDistributionChart() {
        const canvas = this.canvasRefs.amountDistribution.el;
        if (!canvas) return;
        this.destroyChart("amountDistribution");
        const rows = this.state.data.amount_distribution;
        if (!rows.length) return;

        this.charts.amountDistribution = new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [
                    {
                        label: "Commandes",
                        data: rows.map((r) => r.count),
                        borderColor: "#5C6AC4",
                        backgroundColor: "rgba(92, 106, 196, 0.12)",
                        borderWidth: 2.5,
                        tension: 0.35,
                        fill: true,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `  ${ctx.parsed.y} commande(s)`,
                        },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { precision: 0 },
                    },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    renderShopChart() {
        const canvas = this.canvasRefs.shop.el;
        if (!canvas) return;
        this.destroyChart("shop");
        const rows = this.state.data.revenue_by_shop;
        if (!rows.length) return;

        this.charts.shop = new Chart(canvas.getContext("2d"), {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.name),
                datasets: [
                    {
                        data: rows.map((r) => r.revenue),
                        backgroundColor: rows.map((_, i) => SHOP_COLORS[i % SHOP_COLORS.length]),
                        borderWidth: 2,
                        borderColor: "#fff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 12 } },
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.label} : ${this.formatMoney(ctx.parsed)}` },
                    },
                },
            },
        });
    }

    renderProductsChart() {
        const canvas = this.canvasRefs.products.el;
        if (!canvas) return;
        this.destroyChart("products");
        const rows = [...this.state.data.top_products].reverse();
        if (!rows.length) return;

        this.charts.products = new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: rows.map((r) => (r.name.length > 28 ? r.name.slice(0, 26) + "…" : r.name)),
                datasets: [
                    {
                        label: "CA",
                        data: rows.map((r) => r.revenue),
                        backgroundColor: "#5C6AC4",
                        borderRadius: 4,
                        barThickness: 14,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => this.formatMoney(ctx.parsed.x) } },
                },
                scales: {
                    x: { grid: { color: "rgba(0,0,0,0.05)" }, ticks: { callback: (v) => this.formatMoney(v) } },
                    y: { grid: { display: false } },
                },
            },
        });
    }
}

registry.category("actions").add("shopify_sales_dashboard", ShopifyDashboard);
