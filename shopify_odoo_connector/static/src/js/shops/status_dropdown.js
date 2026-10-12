/** @odoo-module **/
/**
 * Widget « shopify_status_dropdown » : badge de couleur plein ; un clic
 * ouvre une liste de choix (point de couleur + libellé), comme sur un
 * tableau de projet. Le choix est enregistré tout de suite.
 *
 * Options (attribut options="{...}" dans la vue) :
 *   colors : {valeur: "red"|"orange"|"green"|"blue"|"purple"|"gray"|"navy"}
 *   auto_field : champ booléen « statut automatique » (affiche une entrée
 *                « Automatique » pour revenir au calcul)
 *   auto_action : méthode serveur appelée pour revenir en automatique
 */
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

const DEFAULT_COLORS = {
    off: "red", risk: "orange", ok: "green", pause: "blue", done: "purple",
    error: "red", cancel: "red", draft: "gray", connected: "blue",
};

export class ShopifyStatusDropdown extends Component {
    static template = "shopify_odoo_connector.ShopifyStatusDropdown";
    static components = { Dropdown, DropdownItem };
    static props = {
        ...standardFieldProps,
        colors: { type: Object, optional: true },
        autoField: { type: String, optional: true },
        autoAction: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get options() {
        return this.props.record.fields[this.props.name].selection || [];
    }

    get label() {
        const opt = this.options.find((o) => o[0] === this.value);
        return opt ? opt[1] : "—";
    }

    colorOf(value) {
        return (this.props.colors && this.props.colors[value]) || DEFAULT_COLORS[value] || "gray";
    }

    get isAuto() {
        return this.props.autoField ? Boolean(this.props.record.data[this.props.autoField]) : false;
    }

    get canEdit() {
        return !this.props.readonly || this.props.record.fields[this.props.name].readonly === false;
    }

    async _refresh() {
        await this.props.record.load();
        // Compteurs de la barre en haut de la page
        this.env.bus.trigger("SHOPIFY:STATUS_CHANGED");
    }

    async select(value) {
        const record = this.props.record;
        if (value === this.value && !this.isAuto) {
            return;
        }
        // Écriture directe : la ligne ne passe pas en mode « modification ».
        await this.orm.write(record.resModel, [record.resId], { [this.props.name]: value });
        await this._refresh();
    }

    async backToAuto() {
        const record = this.props.record;
        if (this.props.autoAction) {
            await this.orm.call(record.resModel, this.props.autoAction, [[record.resId]]);
            await this._refresh();
        }
    }
}

export const shopifyStatusDropdown = {
    component: ShopifyStatusDropdown,
    displayName: "Statut (liste de choix colorée)",
    supportedTypes: ["selection"],
    extractProps: ({ options }) => ({
        colors: options.colors,
        autoField: options.auto_field,
        autoAction: options.auto_action,
    }),
};

registry.category("fields").add("shopify_status_dropdown", shopifyStatusDropdown);
