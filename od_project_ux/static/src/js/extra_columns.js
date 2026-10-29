/** @odoo-module **/

/**
 * Extra columns for the Monday-style tables (Projets / Tâches / Mes tâches).
 *
 * Lets a project manager add any existing database field of the table's
 * model (project.project or project.task) as a new column, then view and
 * edit it inline. The column list is stored server side in
 * `od.board.column`, so it is shared by every user of the table.
 *
 *  - OdColumnPicker : the "+" button at the end of the header row
 *  - OdExtraHeader  : the header cell of an extra column (rename-free, removable)
 *  - OdExtraCell    : one editable cell, rendered according to the field type
 */

import { Component, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export const EXTRA_COL_WIDTH = 170;
export const ADD_COL_WIDTH = 44;

const MODEL = "od.board.column";

export const TYPE_INFO = {
    char: { label: "Texte", icon: "fa-font" },
    text: { label: "Texte long", icon: "fa-align-left" },
    integer: { label: "Nombre entier", icon: "fa-hashtag" },
    float: { label: "Nombre décimal", icon: "fa-hashtag" },
    monetary: { label: "Montant", icon: "fa-money" },
    boolean: { label: "Case à cocher", icon: "fa-check-square-o" },
    date: { label: "Date", icon: "fa-calendar" },
    datetime: { label: "Date et heure", icon: "fa-clock-o" },
    selection: { label: "Liste de choix", icon: "fa-list-ul" },
    many2one: { label: "Lien", icon: "fa-link" },
    many2many: { label: "Liens multiples", icon: "fa-tags" },
};

const SELECTION_PALETTE = [
    "#579bfc", "#00c875", "#fdab3d", "#a25ddc", "#e2445c",
    "#0086c0", "#ff642e", "#037f4c", "#9d99b9", "#7f5347",
];

const numberFmt = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

/** Close an open dropdown when the user clicks anywhere outside it. */
function useClickOutside(rootRef, close) {
    useExternalListener(
        window,
        "mousedown",
        (ev) => {
            if (rootRef.el && !rootRef.el.contains(ev.target)) close();
        },
        { capture: true }
    );
}

/** Shared helpers for the parent tables (Board + Portfolio). */
export async function loadExtraColumns(orm, resModel, recordIds) {
    const { columns, can_manage } = await orm.call(MODEL, "od_get_columns", [resModel]);
    const values = columns.length && recordIds.length
        ? await orm.call(MODEL, "od_read_values", [resModel, recordIds])
        : {};
    return { columns, canManage: can_manage, values };
}

export async function readExtraValues(orm, resModel, recordIds, fieldNames) {
    if (!recordIds.length) return {};
    return orm.call(MODEL, "od_read_values", [resModel, recordIds, fieldNames || null]);
}

export function mergeExtraValues(target, incoming) {
    for (const [id, fields] of Object.entries(incoming || {})) {
        target[id] = Object.assign({}, target[id] || {}, fields);
    }
}

export async function removeExtraColumn(orm, column) {
    await orm.call(MODEL, "od_remove_column", [column.id]);
}

// ----------------------------------------------------------------------
// "+" : add a column
// ----------------------------------------------------------------------
export class OdColumnPicker extends Component {
    static template = "od_project_ux.ColumnPicker";
    static props = {
        resModel: String,
        onAdd: Function,
        cellClass: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");
        this.searchRef = useRef("search");
        this.state = useState({ open: false, loading: false, fields: [], search: "" });
        useClickOutside(this.root, () => (this.state.open = false));
        useEffect(
            (open) => {
                if (open && this.searchRef.el) this.searchRef.el.focus();
            },
            () => [this.state.open]
        );
    }

    typeInfo(type) {
        return TYPE_INFO[type] || { label: type, icon: "fa-square-o" };
    }

    async toggle() {
        if (this.state.open) {
            this.state.open = false;
            return;
        }
        this.state.open = true;
        this.state.search = "";
        this.state.loading = true;
        this.state.fields = await this.orm.call(MODEL, "od_get_available_fields", [this.props.resModel]);
        this.state.loading = false;
    }

    get filteredFields() {
        const q = this.state.search.trim().toLowerCase();
        if (!q) return this.state.fields;
        return this.state.fields.filter(
            (f) => f.label.toLowerCase().includes(q) || f.name.toLowerCase().includes(q)
        );
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    async add(field) {
        this.state.open = false;
        const column = await this.orm.call(MODEL, "od_add_column", [this.props.resModel, field.name]);
        await this.props.onAdd(column);
    }
}

// ----------------------------------------------------------------------
// Header cell of an extra column
// ----------------------------------------------------------------------
export class OdExtraHeader extends Component {
    static template = "od_project_ux.ExtraHeader";
    static props = {
        column: Object,
        canManage: Boolean,
        onRemove: Function,
        cellClass: { type: String, optional: true },
    };

    setup() {
        this.root = useRef("root");
        this.state = useState({ open: false });
        useClickOutside(this.root, () => (this.state.open = false));
    }

    get icon() {
        return (TYPE_INFO[this.props.column.type] || {}).icon || "fa-square-o";
    }

    get title() {
        const c = this.props.column;
        return `${c.label} (${c.name})${c.help ? " - " + c.help : ""}`;
    }

    toggle() {
        if (this.props.canManage) this.state.open = !this.state.open;
    }

    async remove() {
        this.state.open = false;
        await this.props.onRemove(this.props.column);
    }
}

// ----------------------------------------------------------------------
// One cell of an extra column
// ----------------------------------------------------------------------
export class OdExtraCell extends Component {
    static template = "od_project_ux.ExtraCell";
    static props = {
        resModel: String,
        recordId: Number,
        column: Object,
        cell: { optional: true },
        onUpdate: Function,
        cellClass: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");
        this.inputRef = useRef("input");
        this.state = useState({ open: false, editing: false, draft: "", search: "", options: [] });
        useClickOutside(this.root, () => {
            this.state.open = false;
        });
        useEffect(
            (editing, open) => {
                if ((editing || open) && this.inputRef.el) this.inputRef.el.focus();
            },
            () => [this.state.editing, this.state.open]
        );
    }

    // -------------------------------------------------------- display
    get col() {
        return this.props.column;
    }

    get value() {
        return this.props.cell ? this.props.cell.value : false;
    }

    get readonly() {
        return this.col.readonly;
    }

    get isNumber() {
        return ["integer", "float", "monetary"].includes(this.col.type);
    }

    get isPercent() {
        return this.isNumber && !!this.col.percent;
    }

    get pct() {
        const p = this.props.cell && this.props.cell.pct;
        return typeof p === "number" ? p : 0;
    }

    get pctBarWidth() {
        return Math.max(0, Math.min(100, this.pct));
    }

    get pctColor() {
        const p = this.pct;
        if (p >= 100) return "#00c875";
        if (p >= 50) return "#579bfc";
        if (p > 0) return "#fdab3d";
        return "#c4c4c4";
    }

    get numberDisplay() {
        if (this.value === false || this.value === null || this.value === undefined) return "";
        const txt = numberFmt.format(this.value);
        const cur = this.props.cell && this.props.cell.currency;
        return cur ? `${txt} ${cur}` : txt;
    }

    get selectionLabel() {
        return (this.props.cell && this.props.cell.display) || "";
    }

    selectionColor(key) {
        const idx = this.col.selection.findIndex((o) => o[0] === key);
        return idx === -1 ? "#c4c4c4" : SELECTION_PALETTE[idx % SELECTION_PALETTE.length];
    }

    get m2oDisplay() {
        return (this.props.cell && this.props.cell.display) || "";
    }

    get m2mDisplay() {
        return (this.props.cell && this.props.cell.display) || [];
    }

    // -------------------------------------------------------- saving
    async save(value) {
        const cell = await this.orm.call(MODEL, "od_write_value", [
            this.props.resModel,
            this.props.recordId,
            this.col.name,
            value,
        ]);
        this.props.onUpdate(this.col.name, cell);
    }

    // Text / number: click to edit, Enter or blur to save, Escape to cancel
    startEdit() {
        if (this.readonly) return;
        let draft = this.value;
        if (this.isPercent) draft = this.pct;
        this.state.draft = draft === false || draft === null || draft === undefined ? "" : String(draft);
        this.state.editing = true;
    }

    onDraftInput(ev) {
        this.state.draft = ev.target.value;
    }

    async commit(ev) {
        if (ev && ev.type === "keydown") {
            if (ev.key === "Escape") {
                this.state.editing = false;
                return;
            }
            if (ev.key !== "Enter" || (this.col.type === "text" && ev.shiftKey)) return;
            ev.preventDefault();
        }
        if (!this.state.editing) return;
        this.state.editing = false;
        let value = this.state.draft;
        if (this.isNumber) {
            value = value.trim() === ""
                ? false
                : Number(value.replace(/[\s\u00a0\u202f]/g, "").replace(",", "."));
            if (value !== false && Number.isNaN(value)) return;
        }
        await this.save(value);
    }

    async onToggleBool(ev) {
        await this.save(ev.target.checked);
    }

    async onDateChange(ev) {
        await this.save(ev.target.value || false);
    }

    // Selection / many2one / many2many: dropdown
    async toggleMenu() {
        if (this.readonly) return;
        this.state.open = !this.state.open;
        if (this.state.open && ["many2one", "many2many"].includes(this.col.type)) {
            this.state.search = "";
            await this.searchRecords("");
        }
    }

    async searchRecords(query) {
        if (!this.col.relation) return;
        this.state.options = await this.orm.call(this.col.relation, "name_search", [], {
            name: query,
            limit: 8,
        });
    }

    async onSearchInput(ev) {
        this.state.search = ev.target.value;
        await this.searchRecords(this.state.search);
    }

    async pick(value) {
        this.state.open = false;
        await this.save(value);
    }

    hasM2m(id) {
        return (this.value || []).includes(id);
    }

    async toggleM2m(id) {
        const ids = [...(this.value || [])];
        const idx = ids.indexOf(id);
        if (idx === -1) ids.push(id);
        else ids.splice(idx, 1);
        await this.save(ids);
    }
}
