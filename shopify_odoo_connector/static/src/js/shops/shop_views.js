/** @odoo-module **/
/**
 * Page « Boutiques » : barre d'état en haut des vues liste et kanban
 * (Hors piste / À risque / Sur la bonne voie + totaux). Un clic sur une
 * pastille filtre la vue sur cet état.
 */
import { registry } from "@web/core/registry";
import { useService, useBus } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";

const HEALTH = [
    { key: "off", filter: "health_off", label: "Hors piste" },
    { key: "risk", filter: "health_risk", label: "À risque" },
    { key: "ok", filter: "health_ok", label: "Sur la bonne voie" },
];

export class ShopHealthBar extends Component {
    static template = "shopify_odoo_connector.ShopHealthBar";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null });
        this.health = HEALTH;
        onWillStart(() => this.load());
        useBus(this.env.searchModel, "update", () => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("shopify.config", "get_health_summary", []);
    }

    _item(filterName) {
        return this.env.searchModel
            .getSearchItems((i) => i.type === "filter" && i.name === filterName)[0];
    }

    isActive(filterName) {
        const item = this._item(filterName);
        return Boolean(item && item.isActive);
    }

    toggle(filterName) {
        const item = this._item(filterName);
        if (item) {
            this.env.searchModel.toggleSearchItem(item.id);
        }
    }

    fmt(n) {
        return (n || 0).toLocaleString("fr-FR");
    }
}

export class ShopListController extends ListController {
    static template = "shopify_odoo_connector.ShopListView";
    static components = { ...ListController.components, ShopHealthBar };
}

export class ShopKanbanController extends KanbanController {
    static template = "shopify_odoo_connector.ShopKanbanView";
    static components = { ...KanbanController.components, ShopHealthBar };
}

registry.category("views").add("shopify_shop_list", { ...listView, Controller: ShopListController });
registry.category("views").add("shopify_shop_kanban", { ...kanbanView, Controller: ShopKanbanController });
