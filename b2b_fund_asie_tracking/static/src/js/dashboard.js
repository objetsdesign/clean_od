/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onWillStart, useEffect, onWillUnmount } from "@odoo/owl";

// Couleurs de secours si un libellé de statut n'est pas reconnu.
const FALLBACK_COLORS = ["#4F46E5", "#0D9488", "#D97706", "#E11D48", "#8B5CF6", "#0891B2", "#65A30D"];

// Les couleurs de statut sont choisies pour porter du sens (vert = accepté/livré,
// rouge = refusé/litige, ambre = en attente), plutôt qu'une palette arbitraire.
const STATUS_COLORS = {
    // Devis
    "Accepté": "#059669",
    "Refusé": "#E11D48",
    "En cours": "#4F46E5",
    "Envoyé": "#0891B2",
    "Relancé": "#D97706",
    "Expiré": "#94A3B8",
    "En attente client": "#8B5CF6",
    // Commandes
    "Confirmée": "#4F46E5",
    "En production": "#D97706",
    "Contrôle qualité": "#8B5CF6",
    "Prête à expédier": "#0891B2",
    "Expédiée": "#2563EB",
    "Livrée": "#059669",
    "Litige": "#E11D48",
    "Annulée": "#94A3B8",
};

function colorFor(label, index) {
    return STATUS_COLORS[label] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

// Plugin Chart.js maison : affiche le total au centre des donuts, pour que le
// chiffre-clé soit lisible sans devoir déchiffrer la légende.
const centerTextPlugin = {
    id: "b2faCenterText",
    afterDraw(chart) {
        if (chart.config.type !== "doughnut") {
            return;
        }
        const { ctx, chartArea } = chart;
        if (!chartArea) {
            return;
        }
        const total = (chart.data.datasets[0]?.data || []).reduce((a, b) => a + b, 0);
        const cx = (chartArea.left + chartArea.right) / 2;
        const cy = (chartArea.top + chartArea.bottom) / 2;
        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#0F1222";
        ctx.font = "700 22px -apple-system, Helvetica, Arial, sans-serif";
        ctx.fillText(String(total), cx, cy - 8);
        ctx.fillStyle = "#8A90A6";
        ctx.font = "600 10.5px -apple-system, Helvetica, Arial, sans-serif";
        ctx.fillText("TOTAL", cx, cy + 12);
        ctx.restore();
    },
};

class B2faDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            data: null,
            loading: true,
        });
        this.rootRef = useRef("root");
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

    scrollToSection(activityCode) {
        // Cherche dans le sous-arbre du composant (pas document.getElementById) :
        // Odoo garde parfois une instance précédente du tableau de bord dans le
        // DOM (pile des breadcrumbs), et un id global renverrait alors la
        // mauvaise section, invisible, ce qui donne l'impression que le scroll
        // "ne marche pas".
        const root = this.rootRef.el;
        const target = root && root.querySelector(`[data-section="${activityCode}"]`);
        if (!target) {
            return;
        }
        const scrollParent = this._getScrollParent(target);
        const OFFSET = 12; // petit espace au-dessus de la carte ciblée
        if (scrollParent === window || scrollParent === document.body) {
            const top = target.getBoundingClientRect().top + window.pageYOffset - OFFSET;
            window.scrollTo({ top, behavior: "smooth" });
        } else {
            const parentRect = scrollParent.getBoundingClientRect();
            const targetRect = target.getBoundingClientRect();
            const top = scrollParent.scrollTop + (targetRect.top - parentRect.top) - OFFSET;
            scrollParent.scrollTo({ top, behavior: "smooth" });
        }
    }

    // Remonte les parents jusqu'à trouver le conteneur qui scrolle réellement
    // (utile car Odoo place le contenu de l'action dans un div interne avec
    // overflow, pas toujours la fenêtre elle-même).
    _getScrollParent(node) {
        let el = node.parentElement;
        while (el) {
            const style = window.getComputedStyle(el);
            const overflowY = style.overflowY;
            const canScroll = (overflowY === "auto" || overflowY === "scroll") && el.scrollHeight > el.clientHeight;
            if (canScroll) {
                return el;
            }
            el = el.parentElement;
        }
        return window;
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
        const activityColors = this.state.data.sections.map((s) => s.color);
        this.charts.bar = new window.Chart(canvas, {
            type: "bar",
            data: {
                labels: charts.activity_labels,
                datasets: [
                    {
                        label: "Montant devis (€)",
                        data: charts.amount_quotes_by_activity,
                        backgroundColor: activityColors.map((c) => `${c}55`),
                        borderColor: activityColors,
                        borderWidth: 1.5,
                        borderRadius: 6,
                        maxBarThickness: 46,
                    },
                    {
                        label: "CA commandes (€)",
                        data: charts.ca_orders_by_activity,
                        backgroundColor: activityColors,
                        borderRadius: 6,
                        maxBarThickness: 46,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 }, usePointStyle: true, pointStyle: "circle" } },
                    tooltip: {
                        backgroundColor: "#0F1222",
                        padding: 10,
                        cornerRadius: 8,
                        titleFont: { size: 12, weight: "700" },
                        bodyFont: { size: 12 },
                    },
                },
                scales: {
                    y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: "#EEF0F6" } },
                    x: { ticks: { font: { size: 11, weight: "600" } }, grid: { display: false } },
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
                        backgroundColor: labels.map((l, i) => colorFor(l, i)),
                        borderWidth: 2,
                        borderColor: "#fff",
                        hoverOffset: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10.5 }, usePointStyle: true, pointStyle: "circle" } },
                    tooltip: {
                        backgroundColor: "#0F1222",
                        padding: 10,
                        cornerRadius: 8,
                    },
                },
            },
            plugins: [centerTextPlugin],
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
