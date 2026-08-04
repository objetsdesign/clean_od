/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, useState, onWillStart } from "@odoo/owl";

export class OdooDashboard extends Component {
    static template = "odoo_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.notificationService = useService("notification");

        this.state = useState({
            modules: [],
            counts: {},
            selected: null,
            records: [],
            fieldDefs: [],
            loading: true,
            loadingRecords: false,
            totalRecords: 0,
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        const [modules, counts] = await Promise.all([
            this.orm.call("odoo.dashboard", "get_modules_config", []),
            this.orm.call("odoo.dashboard", "get_dashboard_counts", []),
        ]);
        this.state.modules = modules;
        this.state.counts = counts;
        this.state.totalRecords = Object.values(counts).reduce((a, b) => a + b, 0);
        this.state.loading = false;
        const firstInstalled = modules.find((m) => m.installed) || modules[0];
        if (firstInstalled) {
            await this.selectModule(firstInstalled.key);
        }
    }

    async selectModule(key) {
        this.state.selected = key;
        this.state.loadingRecords = true;
        const data = await this.orm.call("odoo.dashboard", "get_module_records", [key]);
        this.state.records = data.records || [];
        this.state.fieldDefs = data.field_defs || [];
        this.state.loadingRecords = false;
    }

    get currentModule() {
        return this.state.modules.find((m) => m.key === this.state.selected) || {};
    }

    async openFullView() {
        if (!this.state.selected) {
            return;
        }
        const action = await this.orm.call("odoo.dashboard", "get_module_action", [this.state.selected]);
        this.actionService.doAction(action);
    }

    async openRecord(recordId) {
        if (!this.state.selected) {
            return;
        }
        const action = await this.orm.call("odoo.dashboard", "get_module_action", [this.state.selected]);
        this.actionService.doAction({
            ...action,
            views: [[false, "form"]],
            view_mode: "form",
            res_id: recordId,
        });
    }

    async refresh() {
        await this.loadDashboard();
    }

    async refreshCounts() {
        const counts = await this.orm.call("odoo.dashboard", "get_dashboard_counts", []);
        this.state.counts = counts;
        this.state.totalRecords = Object.values(counts).reduce((a, b) => a + b, 0);
    }

    /**
     * Ouvre le formulaire de création standard du module sélectionné
     * (ex: nouveau devis pour "Ventes"), dans une fenêtre modale.
     * Rafraîchit automatiquement la liste et les compteurs à la fermeture.
     */
    async createRecord() {
        const mod = this.currentModule;
        if (!mod || !mod.model) {
            return;
        }
        if (!mod.installed) {
            this.notificationService.add("Ce module n'est pas installé.", { type: "warning" });
            return;
        }
        await this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                res_model: mod.model,
                views: [[false, "form"]],
                target: "new",
                context: {},
            },
            {
                onClose: async () => {
                    await this.selectModule(this.state.selected);
                    await this.refreshCounts();
                },
            }
        );
    }

    /**
     * Supprime un enregistrement après confirmation, puis rafraîchit
     * la liste et les compteurs. Respecte les droits d'accès réels de
     * l'utilisateur connecté (pas de sudo côté client).
     */
    deleteRecord(recordId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const mod = this.currentModule;
        this.dialogService.add(ConfirmationDialog, {
            title: "Confirmer la suppression",
            body: "Voulez-vous vraiment supprimer cet enregistrement ? Cette action est irréversible.",
            confirmLabel: "Supprimer",
            confirmClass: "btn-danger",
            cancelLabel: "Annuler",
            confirm: async () => {
                try {
                    await this.orm.unlink(mod.model, [recordId]);
                    this.notificationService.add("Enregistrement supprimé.", { type: "success" });
                } catch (e) {
                    this.notificationService.add(
                        "Suppression impossible (droits insuffisants ou enregistrement lié).",
                        { type: "danger" }
                    );
                }
                await this.selectModule(this.state.selected);
                await this.refreshCounts();
            },
            cancel: () => {},
        });
    }

    getFieldValue(record, fname) {
        const val = record[fname];
        if (Array.isArray(val)) {
            return val[1];
        }
        if (val === false || val === undefined || val === null || val === "") {
            return "-";
        }
        return val;
    }

    getStateBadgeClass(record, fname) {
        if (fname !== "state" && fname !== "priority") {
            return "";
        }
        const val = String(record[fname] || "").toLowerCase();
        if (["done", "posted", "paid", "sale", "confirmed", "3"].includes(val)) {
            return "o_badge_success";
        }
        if (["cancel", "cancelled", "0"].includes(val)) {
            return "o_badge_danger";
        }
        return "o_badge_neutral";
    }
}

registry.category("actions").add("odoo_dashboard_client_action", OdooDashboard);
