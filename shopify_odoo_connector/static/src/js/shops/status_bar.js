/** @odoo-module **/
/**
 * Design « tableau de statuts » pour toutes les listes ouvertes depuis les
 * menus Shopify. Activé par le contexte de l'action :
 *   'shopify_list': 1                      -> style coloré (classe o_shopify_list)
 *   'shopify_status_field': 'state'        -> barre de pastilles + compteurs
 *   'shopify_list_title': 'Commandes'      -> titre de la barre (optionnel)
 * Les listes standard d'Odoo ouvertes hors menus Shopify ne changent pas.
 */
import { patch } from "@web/core/utils/patch";
import { useService, useBus } from "@web/core/utils/hooks";
import { Domain } from "@web/core/domain";
import { Component, useState, onWillStart } from "@odoo/owl";
import { ListController } from "@web/views/list/list_controller";

// Couleur de chaque valeur de statut (clé technique -> teinte)
const TONE = {
    success: ["sale", "done", "paid", "posted", "processed", "success", "connected", "ok",
        "fulfilled", "delivered", "reversed", "in_payment"],
    warning: ["draft", "sent", "waiting", "confirmed", "received", "pending", "partial",
        "partially_paid", "risk", "authorized", "partially_refunded"],
    danger: ["cancel", "error", "off", "not_paid", "refunded", "voided", "failure", "failed"],
};

// Statuts financiers Shopify (champ texte) : libellés en français
const FR_LABELS = {
    paid: "Payée", pending: "En attente", authorized: "Autorisée", partially_paid: "Partiellement payée",
    refunded: "Remboursée", partially_refunded: "Remboursée en partie", voided: "Annulée", unpaid: "Non payée",
};

export function shopifyTone(value) {
    const v = String(value || "").toLowerCase();
    for (const [tone, keys] of Object.entries(TONE)) {
        if (keys.includes(v)) {
            return tone;
        }
    }
    return v ? "info" : "muted";
}

export class ShopifyStatusBar extends Component {
    static template = "shopify_odoo_connector.ShopifyStatusBar";
    static props = ["resModel", "fields", "context"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ items: [], total: 0 });
        onWillStart(() => this.load());
        useBus(this.env.searchModel, "update", () => this.load());
        useBus(this.env.bus, "SHOPIFY:STATUS_CHANGED", () => this.load());
    }

    get field() {
        return this.props.context.shopify_status_field;
    }

    get title() {
        return this.props.context.shopify_list_title || "";
    }

    labelOf(value) {
        const def = this.props.fields[this.field] || {};
        if (def.selection) {
            const opt = def.selection.find((o) => o[0] === value);
            if (opt) {
                return opt[1];
            }
        }
        return FR_LABELS[value] || value || "Non défini";
    }

    async load() {
        if (!this.field || !this.props.fields[this.field]) {
            return;
        }
        // Compteurs sur tout le périmètre de l'action (pas seulement le filtre
        // de statut actif), comme sur un tableau de projet.
        const domain = this.env.searchModel.globalDomain || [];
        const groups = await this.orm.readGroup(
            this.props.resModel, domain, [this.field], [this.field], { lazy: true }
        );
        let total = 0;
        this.state.items = groups.map((g) => {
            const raw = g[this.field];
            const value = Array.isArray(raw) ? raw[0] : raw;
            const count = g[`${this.field}_count`] || g.__count || 0;
            total += count;
            return { value, label: this.labelOf(value), count, tone: shopifyTone(value) };
        });
        this.state.total = total;
    }

    _filterFor(value) {
        return Object.values(this.env.searchModel.searchItems).find(
            (i) => i.shopifyStatusField === this.field && i.shopifyStatusValue === value
        );
    }

    isActive(value) {
        const item = this._filterFor(value);
        return Boolean(item && this.env.searchModel.query.some((q) => q.searchItemId === item.id));
    }

    toggle(item) {
        const existing = this._filterFor(item.value);
        if (existing) {
            this.env.searchModel.toggleSearchItem(existing.id);
            return;
        }
        this.env.searchModel.createNewFilters([{
            description: item.label,
            domain: new Domain([[this.field, "=", item.value]]).toString(),
            shopifyStatusField: this.field,
            shopifyStatusValue: item.value,
        }]);
    }

    fmt(n) {
        return (n || 0).toLocaleString("fr-FR");
    }
}

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this.ShopifyStatusBar = ShopifyStatusBar;
    },
    get className() {
        const base = super.className || "";
        return this.props.context && this.props.context.shopify_list ? `${base} o_shopify_list` : base;
    },
    get shopifyShowStatusBar() {
        const ctx = this.props.context || {};
        return Boolean(ctx.shopify_list && ctx.shopify_status_field);
    },
});
