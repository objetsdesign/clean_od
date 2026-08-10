/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onWillStart, useEffect, onWillUnmount } from "@odoo/owl";

const CHART_COLORS = ["#2563eb", "#16a34a", "#dc2626", "#d97706", "#8b5cf6", "#0891b2", "#db2777", "#65a30d", "#4b5563"];

class B2faDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            data: null,
            loading: true,
        });
        this.barChartRef = useRef("barChart");
        this.orderPieChartRef = useRef("orderPieChart");
        this.quotePieChartRef = useRef("quotePieChart");
        this.charts = {};

        onWillStart(async () => {
            await this.loadData();
        });

        useEffect(
            () => {
                if (this.state.data && !this.state.loading) {
                    this.renderCharts();
                }
            },
            () => [this.state.data, this.state.loading]
        );

        onWillUnmount(() => {
            Object.values(this.charts).forEach((c) => c && c.destroy());
        });
    }

    async loadData() {
        this.state.loading = true;
        const data = await this.orm.call("b2fa.dashboard", "get_dashboard_data", []);
        this.state.data = data;
        this.state.loading = false;
    }

    formatMoney(value) {
        const num = Math.round(value || 0);
        const formatted = new Intl.NumberFormat("fr-FR").format(num);
        const symbol = (this.state.data && this.state.data.currency_symbol) || "€";
        const position = (this.state.data && this.state.data.currency_position) || "after";
        return position === "before" ? `${symbol}\u00A0${formatted}` : `${formatted}\u00A0${symbol}`;
    }

    formatNumber(value) {
        return new Intl.NumberFormat("fr-FR").format(Math.round(value || 0));
    }

    renderCharts() {
        this.renderBarChart();
        this.renderPieChart(this.orderPieChartRef, "order", this.state.data.charts.order_status_distribution);
        this.renderPieChart(this.quotePieChartRef, "quote", this.state.data.charts.quote_status_distribution);
    }

    renderBarChart() {
        const canvas = this.barChartRef.el;
        if (!canvas || !window.Chart) {
            return;
        }
        if (this.charts.bar) {
            this.charts.bar.destroy();
        }
        const charts = this.state.data.charts;
        this.charts.bar = new window.Chart(canvas, {
            type: "bar",
            data: {
                labels: charts.activity_labels,
                datasets: [
                    {
                        label: "Montant devis (€)",
                        data: charts.amount_quotes_by_activity,
                        backgroundColor: "#93c5fd",
                        borderRadius: 6,
                    },
                    {
                        label: "CA commandes (€)",
                        data: charts.ca_orders_by_activity,
                        backgroundColor: "#2563eb",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
                },
                scales: {
                    y: { beginAtZero: true, ticks: { font: { size: 10 } } },
                    x: { ticks: { font: { size: 11 } } },
                },
            },
        });
    }

    renderPieChart(ref, key, distribution) {
        const canvas = ref.el;
        if (!canvas || !window.Chart) {
            return;
        }
        if (this.charts[key]) {
            this.charts[key].destroy();
        }
        const labels = Object.keys(distribution || {});
        const values = Object.values(distribution || {});
        this.charts[key] = new window.Chart(canvas, {
            type: "doughnut",
            data: {
                labels,
                datasets: [
                    {
                        data: values,
                        backgroundColor: labels.map((l, i) => CHART_COLORS[i % CHART_COLORS.length]),
                        borderWidth: 2,
                        borderColor: "#fff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
                },
            },
        });
    }

    async openQuotes(activityCode) {
        await this.openList("b2fa.quote", activityCode, "Devis");
    }

    async openOrders(activityCode) {
        await this.openList("b2fa.order", activityCode, "Commandes");
    }

    async openList(model, activityCode, label) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: label,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: [["activity_type", "=", activityCode]],
            context: { default_activity_type: activityCode },
        });
    }
}

B2faDashboard.template = "b2b_fund_asie_tracking.Dashboard";

registry.category("actions").add("b2fa_dashboard", B2faDashboard);

export default B2faDashboard;
