/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ProjectUxDashboard extends Component {
    static template = "od_project_ux.ProjectUxDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            data: {
                active_projects: 0,
                open_tasks: 0,
                overdue_tasks: 0,
                completed_projects: 0,
                average_progress: 0,
                projects: [],
            },
        });

        onWillStart(async () => {
            this.state.data = await this.orm.call(
                "project.project",
                "get_ux_dashboard_data",
                []
            );
            this.state.loading = false;
        });
    }

    openProjects() {
        this.action.doAction("project.open_view_project_all");
    }

    openTasks() {
        this.action.doAction("project.action_view_all_task");
    }

    getStatusClass(status) {
        return {
            on_track: "od_status_success",
            at_risk: "od_status_warning",
            off_track: "od_status_danger",
            on_hold: "od_status_info",
            done: "od_status_done",
        }[status] || "od_status_neutral";
    }
}

registry.category("actions").add(
    "od_project_ux.dashboard",
    ProjectUxDashboard
);
