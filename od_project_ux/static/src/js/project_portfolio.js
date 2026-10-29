/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    ADD_COL_WIDTH,
    EXTRA_COL_WIDTH,
    OdColumnPicker,
    OdExtraCell,
    OdExtraHeader,
    loadExtraColumns,
    mergeExtraValues,
    readExtraValues,
    removeExtraColumn,
} from "./extra_columns";

const RES_MODEL = "project.project";

// [key, css track, min width in px] - mirrors $od-pf-cols in project_ux.scss
const BASE_COLS = [
    ["check", "34px", 34],
    ["name", "minmax(200px, 2fr)", 200],
    ["owner", "130px", 130],
    ["health", "150px", 150],
    ["progress", "minmax(200px, 1.3fr)", 200],
    ["priority", "110px", 110],
    ["status", "130px", 130],
    ["timeline", "170px", 170],
];
const ALWAYS_SHOWN = new Set(["check", "name"]);

const HEALTH_COLORS = {
    off_track: "#e2445c",
    at_risk: "#fdab3d",
    on_track: "#00c875",
    on_hold: "#579bfc",
    done: "#a25ddc",
    to_define: "#c4c4c4",
};

const PRIORITY_COLORS = {
    low: "#4ecccc",
    medium: "#0073ea",
    high: "#5559df",
};

const STATUS_COLORS = {
    upcoming: "#323338",
    in_progress: "#fdab3d",
    completed: "#00c875",
    on_hold: "#9d99b9",
};

const AVATAR_PALETTE = [
    "#579bfc", "#a25ddc", "#fdab3d", "#00c875",
    "#e2445c", "#0086c0", "#7f5347", "#037f4c",
];

export class ProjectUxPortfolio extends Component {
    static template = "od_project_ux.ProjectUxPortfolio";
    static components = { OdColumnPicker, OdExtraCell, OdExtraHeader };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            data: { projects: [], priority_options: [], status_options: [], users: [] },
            search: "",
            healthFilter: null,
            groupBy: "none",
            openMenu: null,
            hiddenCols: {},
            newProjectDraft: "",
            addingProject: false,
            extraColumns: [],
            extraValues: {},
            canManageColumns: false,
        });
        this.resModel = RES_MODEL;

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        this.state.data = await this.orm.call("project.project", "get_portfolio_data", []);
        const ids = this.state.data.projects.map((p) => p.id);
        const extra = await loadExtraColumns(this.orm, RES_MODEL, ids);
        this.state.extraColumns = extra.columns;
        this.state.extraValues = extra.values;
        this.state.canManageColumns = extra.canManage;
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Extra columns (fields picked from the database)
    // ------------------------------------------------------------------
    get visibleExtraColumns() {
        return this.state.extraColumns.filter((c) => !this.isColHidden("x_" + c.name));
    }

    /** grid-template-columns shared by the header and every row, so the
     * extra columns line up whatever is hidden / added. */
    get gridStyle() {
        const tracks = [];
        let minWidth = 0;
        for (const [key, track, px] of BASE_COLS) {
            if (ALWAYS_SHOWN.has(key) || !this.isColHidden(key)) {
                tracks.push(track);
                minWidth += px + 8;
            }
        }
        for (const _c of this.visibleExtraColumns) {
            tracks.push(`${EXTRA_COL_WIDTH}px`);
            minWidth += EXTRA_COL_WIDTH + 8;
        }
        tracks.push(`${ADD_COL_WIDTH}px`);
        minWidth += ADD_COL_WIDTH + 24;
        return { template: `grid-template-columns: ${tracks.join(" ")};`, minWidth };
    }

    get rowStyle() {
        return this.gridStyle.template;
    }

    get tableStyle() {
        return `min-width: ${this.gridStyle.minWidth}px;`;
    }

    extraCell(projectId, fieldName) {
        const vals = this.state.extraValues[projectId];
        return vals ? vals[fieldName] : undefined;
    }

    async onExtraColumnAdded(column) {
        this.state.extraColumns.push(column);
        const ids = this.state.data.projects.map((p) => p.id);
        const values = await readExtraValues(this.orm, RES_MODEL, ids, [column.name]);
        mergeExtraValues(this.state.extraValues, values);
    }

    async onExtraColumnRemoved(column) {
        await removeExtraColumn(this.orm, column);
        this.state.extraColumns = this.state.extraColumns.filter((c) => c.id !== column.id);
    }

    onExtraCellUpdate(projectId, fieldName, cell) {
        mergeExtraValues(this.state.extraValues, { [projectId]: { [fieldName]: cell } });
    }

    get hideableColumns() {
        return [
            ["owner", "Responsable"],
            ["health", "Statut du projet"],
            ["progress", "Avancement"],
            ["priority", "Priorité"],
            ["status", "Phase"],
            ["timeline", "Échéancier"],
            ...this.state.extraColumns.map((c) => ["x_" + c.name, c.label]),
        ];
    }

    progressTitle(project) {
        if (!project.task_count) return "Aucune tâche";
        const parts = project.progress_segments.map(
            (s) => `${s.label} : ${s.pct} % (${s.count})`
        );
        return `${project.progress_pct} % terminé (${project.done_count}/${project.task_count} tâches)\n` + parts.join("\n");
    }

    // ------------------------------------------------------------------
    // Derived / filtered rows
    // ------------------------------------------------------------------
    get healthCounts() {
        const counts = { off_track: 0, at_risk: 0, on_track: 0 };
        for (const p of this.state.data.projects) {
            if (p.health in counts) counts[p.health]++;
        }
        return counts;
    }

    get filteredProjects() {
        let rows = this.state.data.projects;
        if (this.state.search.trim()) {
            const q = this.state.search.trim().toLowerCase();
            rows = rows.filter((p) => p.name.toLowerCase().includes(q));
        }
        if (this.state.healthFilter) {
            rows = rows.filter((p) => p.health === this.state.healthFilter);
        }
        return rows;
    }

    get groupedProjects() {
        const rows = this.filteredProjects;
        if (this.state.groupBy === "none") {
            return [{ key: "all", label: null, rows }];
        }
        const keyFn = {
            owner: (p) => (p.owner ? p.owner.name : "Unassigned"),
            priority: (p) => p.priority_label || "None",
            status: (p) => p.status_label || "None",
            health: (p) => p.health_label,
        }[this.state.groupBy];
        const groups = {};
        const order = [];
        for (const p of rows) {
            const key = keyFn(p);
            if (!(key in groups)) {
                groups[key] = [];
                order.push(key);
            }
            groups[key].push(p);
        }
        return order.map((key) => ({ key, label: key, rows: groups[key] }));
    }

    // ------------------------------------------------------------------
    // Toolbar
    // ------------------------------------------------------------------
    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    toggleHealthFilter(health) {
        this.state.healthFilter = this.state.healthFilter === health ? null : health;
    }

    setGroupBy(value) {
        this.state.groupBy = value;
        this.state.openMenu = null;
    }

    get groupByLabel() {
        const labels = {
            owner: "Responsable",
            health: "Statut du projet",
            priority: "Priorité",
            status: "Phase",
        };
        return labels[this.state.groupBy] || "";
    }

    toggleTopMenu(name) {
        this.state.openMenu = this.state.openMenu === name ? null : name;
    }

    isColHidden(col) {
        return !!this.state.hiddenCols[col];
    }

    toggleCol(col) {
        this.state.hiddenCols[col] = !this.state.hiddenCols[col];
    }

    closeMenus() {
        this.state.openMenu = null;
    }

    // ------------------------------------------------------------------
    // Row helpers
    // ------------------------------------------------------------------
    healthColor(health) {
        return HEALTH_COLORS[health] || "#c4c4c4";
    }

    priorityColor(priority) {
        return PRIORITY_COLORS[priority] || "#c4c4c4";
    }

    statusColor(status) {
        return STATUS_COLORS[status] || "#c4c4c4";
    }

    initials(name) {
        if (!name) return "?";
        const parts = name.trim().split(/\s+/);
        return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
    }

    avatarColor(id) {
        return AVATAR_PALETTE[id % AVATAR_PALETTE.length];
    }

    formatRange(project) {
        const fmt = (s) => {
            if (!s) return null;
            const d = new Date(s + "T00:00:00");
            return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
        };
        const start = fmt(project.date_start);
        const end = fmt(project.date_end);
        if (start && end) return `${start} - ${end}`;
        return start || end || "—";
    }

    openProject(projectId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: projectId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------
    // Inline editing
    // ------------------------------------------------------------------
    isMenuOpen(projectId, field) {
        const m = this.state.openMenu;
        return !!m && m.projectId === projectId && m.field === field;
    }

    toggleCellMenu(projectId, field) {
        const cur = this.state.openMenu;
        if (cur && cur.projectId === projectId && cur.field === field) {
            this.state.openMenu = null;
        } else {
            this.state.openMenu = { projectId, field };
        }
    }

    findProject(id) {
        return this.state.data.projects.find((p) => p.id === id);
    }

    async selectHealth(projectId, value) {
        this.state.openMenu = null;
        await this.orm.write("project.project", [projectId], { last_update_status: value });
        const p = this.findProject(projectId);
        if (p) {
            p.health = value;
            p.health_label = { off_track: "Off track", at_risk: "At risk", on_track: "On track", on_hold: "On hold", done: "Done" }[value] || value;
        }
    }

    async selectPriority(projectId, value) {
        this.state.openMenu = null;
        await this.orm.write("project.project", [projectId], { board_priority: value });
        const p = this.findProject(projectId);
        if (p) {
            p.priority = value;
            const opt = this.state.data.priority_options.find((o) => o[0] === value);
            p.priority_label = opt ? opt[1] : value;
        }
    }

    async selectStatus(projectId, value) {
        this.state.openMenu = null;
        await this.orm.write("project.project", [projectId], { board_status: value });
        const p = this.findProject(projectId);
        if (p) {
            p.status = value;
            const opt = this.state.data.status_options.find((o) => o[0] === value);
            p.status_label = opt ? opt[1] : value;
        }
    }

    async selectOwner(projectId, user) {
        this.state.openMenu = null;
        await this.orm.write("project.project", [projectId], { user_id: user.id });
        const p = this.findProject(projectId);
        if (p) p.owner = { id: user.id, name: user.name };
    }

    async onDateChange(projectId, field, ev) {
        const value = ev.target.value || false;
        await this.orm.write("project.project", [projectId], { [field]: value });
        const p = this.findProject(projectId);
        if (p) p[field === "date_start" ? "date_start" : "date_end"] = value;
    }

    // ------------------------------------------------------------------
    // Add project
    // ------------------------------------------------------------------
    startAddProject() {
        this.state.addingProject = true;
    }

    onNewProjectInput(ev) {
        this.state.newProjectDraft = ev.target.value;
    }

    async confirmAddProject(ev) {
        if (ev && ev.type === "keydown" && ev.key !== "Enter") {
            if (ev.key === "Escape") this.state.addingProject = false;
            return;
        }
        const name = this.state.newProjectDraft.trim();
        this.state.addingProject = false;
        this.state.newProjectDraft = "";
        if (!name) return;
        const res = await this.orm.call("project.project", "create_portfolio_project", [name]);
        await this.loadData();
        if (res && res.id) this.openProject(res.id);
    }
}

registry.category("actions").add("od_project_ux.portfolio", ProjectUxPortfolio);
