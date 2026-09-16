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
            viewMode: "board",
            myTasksMode: false,
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
            timelineOffset: 0,
            addingGroup: false,
            newGroupDraft: "",
        });

        this.dayWidth = 34;
        this.timelineDays = 30;

        this._draggedTaskId = null;

        onWillStart(async () => {
            const ctx = (this.props.action && this.props.action.context) || {};
            this.state.myTasksMode = !!ctx.my_tasks_mode;
            const initialProjectId = ctx.default_project_id || ctx.active_id || false;
            await this.loadData(initialProjectId);
        });
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------
    async loadData(projectId) {
        this.state.loading = true;
        const data = this.state.myTasksMode
            ? await this.orm.call("project.task", "get_my_board_data", [])
            : await this.orm.call("project.task", "get_board_data", [projectId || false]);
        this.state.data = data;
        this.state.loading = false;
    }

    /** Field written when a task is dragged/moved to another group:
     * the group is a stage in the normal per-project Board, but a
     * project in the cross-project "Mes tâches" board. */
    get groupField() {
        return this.state.myTasksMode ? "project_id" : "stage_id";
    }

    async switchProject(ev) {
        const projectId = parseInt(ev.target.value, 10);
        await this.loadData(projectId);
    }

    setViewMode(mode) {
        this.state.viewMode = mode;
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

        if (field === "date_deadline" || field === "od_date_start") {
            await this.orm.call("project.task", "set_task_date", [taskId, field, value]);
            task[field] = value;
            return;
        }

        let writeValue = value;
        if (field === "tag_ids" || field === "user_ids") {
            writeValue = [[6, 0, value]];
        }
        await this.orm.write("project.task", [taskId], { [field]: writeValue });

        if (field === "tag_ids") {
            task.tag_ids = this.state.data.tags.filter((t) => value.includes(t.id));
        } else if (field === "user_ids") {
            task.user_ids = this.state.data.users.filter((u) => value.includes(u.id));
        } else if (field === this.groupField) {
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
        await this.updateField(this._draggedTaskId, this.groupField, group.id);
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
        const task = this.state.myTasksMode
            ? await this.orm.call("project.task", "create_my_task", [groupId || false, name])
            : await this.orm.call(
                  "project.task", "create_board_task",
                  [this.state.data.project.id, groupId || false, name]
              );
        const group = this.state.data.groups.find((g) => g.id === groupId);
        if (group) group.tasks.push(task);
    }

    // ------------------------------------------------------------------
    // Add group (stage) - a brand new project has none, so there is
    // otherwise nowhere to even add a first task from this view. Not
    // available in "Mes tâches" mode, where groups are projects.
    // ------------------------------------------------------------------
    startAddGroup() {
        this.state.addingGroup = true;
    }

    onNewGroupInput(ev) {
        this.state.newGroupDraft = ev.target.value;
    }

    async confirmAddGroup(ev) {
        if (ev && ev.type === "keydown" && ev.key !== "Enter") {
            if (ev.key === "Escape") this.state.addingGroup = false;
            return;
        }
        const name = (this.state.newGroupDraft || "").trim();
        this.state.addingGroup = false;
        this.state.newGroupDraft = "";
        if (!name || !this.state.data.project) return;
        const group = await this.orm.call(
            "project.task.type", "create_board_stage",
            [this.state.data.project.id, name]
        );
        this.state.data.groups.push(group);
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

    // ------------------------------------------------------------------
    // Timeline (Gantt-style)
    // ------------------------------------------------------------------
    navigateTimeline(deltaDays) {
        if (deltaDays === 0) {
            this.state.timelineOffset = 0;
        } else {
            this.state.timelineOffset += deltaDays;
        }
    }

    getWindowStart() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        d.setDate(d.getDate() - 7 + this.state.timelineOffset);
        return d;
    }

    get windowDates() {
        const start = this.getWindowStart();
        const days = [];
        for (let i = 0; i < this.timelineDays; i++) {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            days.push(d);
        }
        return days;
    }

    get timelineWidth() {
        return this.timelineDays * this.dayWidth;
    }

    parseDate(str) {
        if (!str) return null;
        const [y, m, d] = str.split("-").map(Number);
        return new Date(y, m - 1, d);
    }

    isToday(date) {
        const t = new Date();
        t.setHours(0, 0, 0, 0);
        return date.getTime() === t.getTime();
    }

    isWeekend(date) {
        const d = date.getDay();
        return d === 0 || d === 6;
    }

    monthLabelFor(date, index) {
        if (index === 0 || date.getDate() === 1) {
            return date.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
        }
        return "";
    }

    taskBarRange(task) {
        const end = this.parseDate(task.date_deadline) || this.parseDate(task.od_date_start) || new Date();
        const start = this.parseDate(task.od_date_start) || end;
        return start.getTime() <= end.getTime() ? { start, end } : { start: end, end: start };
    }

    barStyle(task) {
        const windowStart = this.getWindowStart();
        const { start, end } = this.taskBarRange(task);
        const offsetDays = Math.round((start - windowStart) / 86400000);
        const durationDays = Math.round((end - start) / 86400000) + 1;
        const left = offsetDays * this.dayWidth;
        const width = Math.max(durationDays * this.dayWidth - 4, this.dayWidth - 6);
        return `left:${left}px; width:${width}px; background:${this.statusColor(task.state)};`;
    }

    async onStartDateChange(task, ev) {
        await this.updateField(task.id, "od_date_start", ev.target.value || false);
    }
}

registry.category("actions").add("od_project_ux.board", ProjectUxBoard);
