/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const NUMERIC_TYPES = ["integer", "float", "monetary"];
const DATE_TYPES = ["date", "datetime"];

export class OdooDashboard extends Component {
    static template = "odoo_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notificationService = useService("notification");

        this._m2oTimers = {};

        this.state = useState({
            modules: [],
            counts: {},
            selected: null,
            records: [],
            fieldDefs: [],
            fieldSpecs: [],
            loading: true,
            loadingRecords: false,
            totalRecords: 0,
            // ligne d'ajout inline
            addingRow: false,
            savingRow: false,
            newRowValues: {},
            m2oSearchResults: {},
            // édition inline sur place
            editingId: null,
            editValues: {},
            editM2oResults: {},
            // mini sélecteur Produit + Prix (pour donner un vrai montant
            // au document via une ligne réelle, sur Ventes/Achats/PdV)
            newLineProduct: null,
            newLinePrice: "",
            lineProductResults: [],
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
        this.state.addingRow = false;
        this.state.newRowValues = {};
        this.state.editingId = null;
        this.state.editValues = {};
        this.state.loadingRecords = true;
        const [data, specs] = await Promise.all([
            this.orm.call("odoo.dashboard", "get_module_records", [key]),
            this.orm.call("odoo.dashboard", "get_module_field_specs", [key]),
        ]);
        this.state.records = data.records || [];
        this.state.fieldDefs = data.field_defs || [];
        this.state.fieldSpecs = specs || [];
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

    // ------------------------------------------------------------------
    // Ajout inline (icône "+")
    // ------------------------------------------------------------------
    startAddRow() {
        if (!this.currentModule.installed) {
            this.notificationService.add("Ce module n'est pas installé.", { type: "warning" });
            return;
        }
        const values = {};
        for (const spec of this.state.fieldSpecs) {
            if (spec.readonly) {
                continue;
            }
            values[spec.name] = spec.type === "boolean" ? false : spec.type === "many2one" ? null : "";
        }
        this.state.newRowValues = values;
        this.state.m2oSearchResults = {};
        this.state.newLineProduct = null;
        this.state.newLinePrice = "";
        this.state.lineProductResults = [];
        this.state.editingId = null;
        this.state.addingRow = true;
    }

    cancelAddRow() {
        this.state.addingRow = false;
        this.state.newRowValues = {};
        this.state.m2oSearchResults = {};
        this.state.newLineProduct = null;
        this.state.newLinePrice = "";
        this.state.lineProductResults = [];
    }

    updateNewRowValue(fieldName, value) {
        this.state.newRowValues[fieldName] = value;
    }

    onMany2oneInput(spec, value) {
        this.state.newRowValues[spec.name] = { id: null, name: value };
        clearTimeout(this._m2oTimers[spec.name]);
        this._m2oTimers[spec.name] = setTimeout(() => this.searchMany2one(spec, value), 300);
    }

    async searchMany2one(spec, query) {
        if (!query) {
            this.state.m2oSearchResults[spec.name] = [];
            return;
        }
        try {
            const results = await this.orm.call(spec.relation, "name_search", [], {
                name: query,
                operator: "ilike",
                limit: 8,
            });
            this.state.m2oSearchResults[spec.name] = results.map((r) => ({ id: r[0], name: r[1] }));
        } catch (e) {
            this.state.m2oSearchResults[spec.name] = [];
        }
    }

    selectMany2oneOption(spec, option) {
        this.state.newRowValues[spec.name] = option;
        this.state.m2oSearchResults[spec.name] = [];
    }

    // ------------------------------------------------------------------
    // Mini sélecteur "Produit + Prix" affiché dans la case Montant pour
    // les modules dont le total est calculé à partir de lignes (Ventes,
    // Achats, PdV). Choisir un produit crée une vraie ligne de commande,
    // donc un vrai montant recalculé par Odoo.
    // ------------------------------------------------------------------
    onLineProductInput(value) {
        this.state.newLineProduct = { id: null, name: value };
        clearTimeout(this._m2oTimers.lineProduct);
        this._m2oTimers.lineProduct = setTimeout(() => this.searchLineProduct(value), 300);
    }

    async searchLineProduct(query) {
        if (!query) {
            this.state.lineProductResults = [];
            return;
        }
        try {
            const results = await this.orm.call("product.product", "name_search", [], {
                name: query,
                operator: "ilike",
                limit: 8,
            });
            this.state.lineProductResults = results.map((r) => ({ id: r[0], name: r[1] }));
        } catch (e) {
            this.state.lineProductResults = [];
        }
    }

    async selectLineProduct(option) {
        this.state.newLineProduct = option;
        this.state.lineProductResults = [];
        try {
            const data = await this.orm.read("product.product", [option.id], ["list_price"]);
            this.state.newLinePrice = data && data[0] ? data[0].list_price : "";
        } catch (e) {
            this.state.newLinePrice = "";
        }
    }

    updateNewLinePrice(value) {
        this.state.newLinePrice = value;
    }

    _buildValuesFromState(source) {
        const values = {};
        for (const spec of this.state.fieldSpecs) {
            if (spec.readonly) {
                continue;
            }
            const raw = source[spec.name];
            if (spec.type === "many2one") {
                if (raw && raw.id) {
                    values[spec.name] = raw.id;
                }
            } else if (spec.type === "boolean") {
                values[spec.name] = !!raw;
            } else if (NUMERIC_TYPES.includes(spec.type)) {
                if (raw !== "" && raw !== null && raw !== undefined) {
                    values[spec.name] = parseFloat(raw);
                }
            } else if (raw !== "" && raw !== null && raw !== undefined) {
                values[spec.name] = raw;
            }
        }
        return values;
    }

    async saveNewRow() {
        const values = this._buildValuesFromState(this.state.newRowValues);
        // Injecte les valeurs par défaut du filtre du module (ex: move_type
        // = 'out_invoice' pour les Factures), sinon l'enregistrement créé
        // n'apparaîtrait jamais dans la liste filtrée.
        Object.assign(values, this.currentModule.createDefaults || {});
        this.state.savingRow = true;
        try {
            const newIds = await this.orm.create(this.currentModule.model, [values]);
            const newId = Array.isArray(newIds) ? newIds[0] : newIds;

            // Si un produit a été choisi dans la case Montant, on crée une
            // vraie ligne de commande pour donner un total réel au document.
            if (this.currentModule.lineModel && this.state.newLineProduct && this.state.newLineProduct.id) {
                const lineVals = {
                    [this.currentModule.lineOrderField]: newId,
                    product_id: this.state.newLineProduct.id,
                    [this.currentModule.lineQtyField]: 1,
                };
                const price = parseFloat(this.state.newLinePrice);
                if (!isNaN(price)) {
                    lineVals.price_unit = price;
                }
                try {
                    await this.orm.create(this.currentModule.lineModel, [lineVals]);
                } catch (e) {
                    this.notificationService.add(
                        "Ligne créée, mais l'ajout du produit a échoué (vérifiez le produit choisi).",
                        { type: "warning" }
                    );
                }
            }

            this.notificationService.add("Ligne ajoutée.", { type: "success" });
            this.cancelAddRow();
            await this.selectModule(this.state.selected);
            await this.refreshCounts();
        } catch (e) {
            this.notificationService.add(
                "Création impossible : vérifiez les champs obligatoires.",
                { type: "danger" }
            );
        }
        this.state.savingRow = false;
    }

    // ------------------------------------------------------------------
    // Édition inline sur place (icône crayon)
    // ------------------------------------------------------------------
    startEditRow(rec, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const values = {};
        for (const spec of this.state.fieldSpecs) {
            if (spec.readonly) {
                continue;
            }
            const raw = rec[spec.name];
            if (spec.type === "many2one") {
                values[spec.name] = Array.isArray(raw) ? { id: raw[0], name: raw[1] } : null;
            } else if (spec.type === "boolean") {
                values[spec.name] = !!raw;
            } else if (DATE_TYPES.includes(spec.type)) {
                values[spec.name] = raw ? String(raw).slice(0, 10) : "";
            } else if (raw === false || raw === undefined || raw === null) {
                values[spec.name] = "";
            } else {
                values[spec.name] = raw;
            }
        }
        this.state.editValues = values;
        this.state.editM2oResults = {};
        this.state.addingRow = false;
        this.state.editingId = rec.id;
    }

    cancelEditRow(ev) {
        if (ev) {
            ev.stopPropagation();
        }
        this.state.editingId = null;
        this.state.editValues = {};
        this.state.editM2oResults = {};
    }

    updateEditValue(fieldName, value) {
        this.state.editValues[fieldName] = value;
    }

    onEditMany2oneInput(spec, value) {
        this.state.editValues[spec.name] = { id: null, name: value };
        clearTimeout(this._m2oTimers["edit_" + spec.name]);
        this._m2oTimers["edit_" + spec.name] = setTimeout(
            () => this.searchEditMany2one(spec, value),
            300
        );
    }

    async searchEditMany2one(spec, query) {
        if (!query) {
            this.state.editM2oResults[spec.name] = [];
            return;
        }
        try {
            const results = await this.orm.call(spec.relation, "name_search", [], {
                name: query,
                operator: "ilike",
                limit: 8,
            });
            this.state.editM2oResults[spec.name] = results.map((r) => ({ id: r[0], name: r[1] }));
        } catch (e) {
            this.state.editM2oResults[spec.name] = [];
        }
    }

    selectEditMany2oneOption(spec, option) {
        this.state.editValues[spec.name] = option;
        this.state.editM2oResults[spec.name] = [];
    }

    async saveEditRow(recordId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const values = this._buildValuesFromState(this.state.editValues);
        this.state.savingRow = true;
        try {
            await this.orm.write(this.currentModule.model, [recordId], values);
            this.notificationService.add("Ligne mise à jour.", { type: "success" });
            this.cancelEditRow();
            await this.selectModule(this.state.selected);
            await this.refreshCounts();
        } catch (e) {
            this.notificationService.add(
                "Mise à jour impossible : vérifiez les valeurs saisies.",
                { type: "danger" }
            );
        }
        this.state.savingRow = false;
    }

    // ------------------------------------------------------------------
    // Suppression inline (icône "-")
    // ------------------------------------------------------------------
    async deleteRecord(recordId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        try {
            await this.orm.unlink(this.currentModule.model, [recordId]);
            this.notificationService.add("Ligne supprimée.", { type: "success" });
        } catch (e) {
            this.notificationService.add(
                "Suppression impossible (droits insuffisants ou enregistrement lié).",
                { type: "danger" }
            );
        }
        await this.selectModule(this.state.selected);
        await this.refreshCounts();
    }

    // ------------------------------------------------------------------
    // Affichage
    // ------------------------------------------------------------------
    isDateType(spec) {
        return DATE_TYPES.includes(spec.type);
    }

    isNumericType(spec) {
        return NUMERIC_TYPES.includes(spec.type);
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
