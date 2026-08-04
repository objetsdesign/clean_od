/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";

export class OdooDashboardStats extends Component {
    static template = "odoo_dashboard.DashboardStats";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.barCanvasRef = useRef("barCanvas");
        this.doughnutCanvasRef = useRef("doughnutCanvas");
        this.barChart = null;
        this.doughnutChart = null;

        this.state = useState({
            modules: [],
            counts: {},
            total: 0,
            loading: true,
            chartError: false,
        });

        onWillStart(async () => {
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                this.state.chartError = true;
            }
            const [modules, counts] = await Promise.all([
                this.orm.call("odoo.dashboard", "get_modules_config", []),
                this.orm.call("odoo.dashboard", "get_dashboard_counts", []),
            ]);
            this.state.modules = modules.filter((m) => m.installed);
            this.state.counts = counts;
            this.state.total = Object.values(counts).reduce((a, b) => a + b, 0);
            this.state.loading = false;
        });

        onMounted(() => {
            if (!this.state.chartError) {
                this.renderCharts();
            }
        });

        onWillUnmount(() => {
            if (this.barChart) {
                this.barChart.destroy();
            }
            if (this.doughnutChart) {
                this.doughnutChart.destroy();
            }
        });
    }

    renderCharts() {
        if (!this.state.modules.length || !this.barCanvasRef.el || !this.doughnutCanvasRef.el) {
            return;
        }
        const labels = this.state.modules.map((m) => m.label);
        const data = this.state.modules.map((m) => this.state.counts[m.key] || 0);
        const colors = this.state.modules.map((m) => m.color);

        this.barChart = new Chart(this.barCanvasRef.el.getContext("2d"), {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Enregistrements",
                        data,
                        backgroundColor: colors,
                        borderRadius: 8,
                        maxBarThickness: 46,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#2c2c3a",
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        grid: { color: "#eeeef5" },
                    },
                    x: {
                        grid: { display: false },
                    },
                },
            },
        });

        this.doughnutChart = new Chart(this.doughnutCanvasRef.el.getContext("2d"), {
            type: "doughnut",
            data: {
                labels,
                datasets: [
                    {
                        data,
                        backgroundColor: colors,
                        borderWidth: 3,
                        borderColor: "#ffffff",
                        hoverOffset: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { boxWidth: 12, padding: 14, font: { size: 11.5 } },
                    },
                    tooltip: {
                        backgroundColor: "#2c2c3a",
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
            },
        });
    }

    async openModule(key) {
        const action = await this.orm.call("odoo.dashboard", "get_module_action", [key]);
        this.actionService.doAction(action);
    }

    percent(key) {
        if (!this.state.total) {
            return 0;
        }
        return Math.round(((this.state.counts[key] || 0) / this.state.total) * 100);
    }
}

registry.category("actions").add("odoo_dashboard_stats_action", OdooDashboardStats);
