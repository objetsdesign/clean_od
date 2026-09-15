/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const GROUP_PALETTE = [
    "#579bfc", "#66ccff", "#a25ddc", "#ff642e",
    "#fdab3d", "#ffcb00", "#00c875", "#037f4c",
    "#9d99b9", "#7f5347", "#e2445c", "#0086c0",
];

const STATE_COLORS = {
    "01_in_progress": "#579bfc",
    "02_changes_requested": "#fdab3d",
    "03_approved": "#a25ddc",
    "04_waiting_normal": "#c4c4c4",
    "1_done": "#00c875",
    "1_canceled": "#e2445c",
};

const AVATAR_PALETTE = [
    "#579bfc", "#a25ddc", "#fdab3d", "#00c875",
    "#e2445c", "#0086c0", "#7f5347", "#037f4c",
];

export class ProjectUxBoard extends Component {
    static template = "od_project_ux.ProjectUxBoard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            data: {
                project: false,
                projects: [],
                groups: [],
                tags: [],
                users: [],
                state_options: [],
                priority_options: [],
            },
            collapsed: {},
            editing: null,
            openMenu: null,
            drafts: {},
            colorPickerGroup: null,
        });

        this._draggedTaskId = null;

        onWillStart(async () => {
            const ctx = (this.props.action && this.props.action.context) || {};
            const initialProjectId = ctx.default_project_id || ctx.active_id || false;
            await this.loadData(initialProjectId);
        });
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------
    async loadData(projectId) {
        this.state.loading = true;
        const data = await this.orm.call("project.task", "get_board_data", [projectId || false]);
        this.state.data = data;
        this.state.loading = false;
    }

    async switchProject(ev) {
        const projectId = parseInt(ev.target.value, 10);
        await this.loadData(projectId);
    }

    openProjectForm() {
        if (!this.state.data.project) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: this.state.data.project.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTask(taskId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: taskId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------
    // Presentation helpers
    // ------------------------------------------------------------------
    groupColor(group, index) {
        if (group.board_color !== undefined && group.board_color >= 0) {
            return GROUP_PALETTE[group.board_color % GROUP_PALETTE.length];
        }
        return GROUP_PALETTE[index % GROUP_PALETTE.length];
    }

    statusColor(state) {
        return STATE_COLORS[state] || "#c4c4c4";
    }

    statusLabel(state) {
        const opt = this.state.data.state_options.find((o) => o[0] === state);
        return opt ? opt[1] : state;
    }

    isStarred(task) {
        const opts = this.state.data.priority_options;
        if (!opts.length) return false;
        return task.priority === opts[opts.length - 1][0];
    }

    initials(name) {
        if (!name) return "?";
        const parts = name.trim().split(/\s+/);
        return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
    }

    avatarColor(id) {
        return AVATAR_PALETTE[id % AVATAR_PALETTE.length];
    }

    isCollapsed(groupId) {
        return !!this.state.collapsed[groupId];
    }

    toggleCollapse(groupId) {
        this.state.collapsed[groupId] = !this.state.collapsed[groupId];
    }

    // ------------------------------------------------------------------
    // Inline text editing (task name)
    // ------------------------------------------------------------------
    startEdit(task) {
        this.state.editing = { taskId: task.id, value: task.name };
    }

    onEditInput(ev) {
        if (this.state.editing) this.state.editing.value = ev.target.value;
    }

    async commitEdit(ev) {
        if (ev && ev.type === "keydown" && ev.key !== "Enter") {
            if (ev.key === "Escape") this.state.editing = null;
            return;
        }
        if (!this.state.editing) return;
        const { taskId, value } = this.state.editing;
        this.state.editing = null;
        if (!value || !value.trim()) return;
        await this.updateField(taskId, "name", value.trim());
    }

    // ------------------------------------------------------------------
    // Dropdown menus (status / tags / assignees)
    // ------------------------------------------------------------------
    toggleMenu(taskId, field) {
        const current = this.state.openMenu;
        if (current && current.taskId === taskId && current.field === field) {
            this.state.openMenu = null;
        } else {
            this.state.openMenu = { taskId, field };
        }
    }

    isMenuOpen(taskId, field) {
        const m = this.state.openMenu;
        return !!m && m.taskId === taskId && m.field === field;
    }

    closeMenus() {
        this.state.openMenu = null;
        this.state.colorPickerGroup = null;
    }

    async selectStatus(task, value) {
        this.state.openMenu = null;
        await this.updateField(task.id, "state", value);
    }

    async togglePriority(task) {
        const opts = this.state.data.priority_options;
        if (!opts.length) return;
        const starred = opts[opts.length - 1][0];
        const normal = opts[0][0];
        const value = this.isStarred(task) ? normal : starred;
        await this.updateField(task.id, "priority", value);
    }

    hasTag(task, tagId) {
        return task.tag_ids.some((t) => t.id === tagId);
    }

    async toggleTag(task, tag) {
        const ids = task.tag_ids.map((t) => t.id);
        const idx = ids.indexOf(tag.id);
        if (idx === -1) ids.push(tag.id);
        else ids.splice(idx, 1);
        await this.updateField(task.id, "tag_ids", ids);
    }

    hasUser(task, userId) {
        return task.user_ids.some((u) => u.id === userId);
    }

    async toggleUser(task, user) {
        const ids = task.user_ids.map((u) => u.id);
        const idx = ids.indexOf(user.id);
        if (idx === -1) ids.push(user.id);
        else ids.splice(idx, 1);
        await this.updateField(task.id, "user_ids", ids);
    }

    async onDateChange(task, ev) {
        await this.updateField(task.id, "date_deadline", ev.target.value || false);
    }

    // ------------------------------------------------------------------
    // Writing + local state sync
    // ------------------------------------------------------------------
    findTask(taskId) {
        for (const group of this.state.data.groups) {
            const task = group.tasks.find((t) => t.id === taskId);
            if (task) return { task, group };
        }
        return { task: null, group: null };
    }

    async updateField(taskId, field, value) {
        const { task, group } = this.findTask(taskId);
        if (!task) return;

        let writeValue = value;
        if (field === "tag_ids" || field === "user_ids") {
            writeValue = [[6, 0, value]];
        }
        await this.orm.write("project.task", [taskId], { [field]: writeValue });

        if (field === "tag_ids") {
            task.tag_ids = this.state.data.tags.filter((t) => value.includes(t.id));
        } else if (field === "user_ids") {
            task.user_ids = this.state.data.users.filter((u) => value.includes(u.id));
        } else if (field === "stage_id") {
            const targetGroup = this.state.data.groups.find((g) => g.id === value);
            if (targetGroup && group) {
                group.tasks = group.tasks.filter((t) => t.id !== taskId);
                task.stage_id = value;
                targetGroup.tasks.push(task);
            }
        } else {
            task[field] = writeValue;
        }
    }

    // ------------------------------------------------------------------
    // Drag & drop between groups
    // ------------------------------------------------------------------
    onDragStart(ev, task) {
        this._draggedTaskId = task.id;
        ev.dataTransfer.effectAllowed = "move";
    }

    onDragOver(ev) {
        ev.preventDefault();
    }

    async onDrop(ev, group) {
        ev.preventDefault();
        if (this._draggedTaskId === null) return;
        await this.updateField(this._draggedTaskId, "stage_id", group.id);
        this._draggedTaskId = null;
    }

    // ------------------------------------------------------------------
    // Add task
    // ------------------------------------------------------------------
    onDraftInput(groupId, ev) {
        this.state.drafts[groupId] = ev.target.value;
    }

    async addTask(groupId, ev) {
        if (ev && ev.type === "keydown" && ev.key !== "Enter") return;
        const name = (this.state.drafts[groupId] || "").trim();
        if (!name) return;
        this.state.drafts[groupId] = "";
        const projectId = this.state.data.project.id;
        const task = await this.orm.call(
            "project.task", "create_board_task", [projectId, groupId || false, name]
        );
        const group = this.state.data.groups.find((g) => g.id === groupId);
        if (group) group.tasks.push(task);
    }

    // ------------------------------------------------------------------
    // Group color picker
    // ------------------------------------------------------------------
    get groupPalette() {
        return GROUP_PALETTE;
    }

    toggleColorPicker(groupId) {
        this.state.colorPickerGroup = this.state.colorPickerGroup === groupId ? null : groupId;
    }

    async pickGroupColor(group, index) {
        this.state.colorPickerGroup = null;
        group.board_color = index;
        await this.orm.call("project.task", "set_board_stage_color", [group.id, index]);
    }
}

registry.category("actions").add("od_project_ux.board", ProjectUxBoard);
