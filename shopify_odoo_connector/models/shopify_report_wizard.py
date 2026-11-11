# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import api, fields, models


class ShopifyReportWizard(models.TransientModel):
    """Fenêtre de rapport (diagnostic, comptes rendus de synchronisation).

    v9.32 : remplace les notifications « collantes » d'Odoo. Celles-ci
    étaient trop étroites pour ces longs rapports : le texte débordait de
    l'écran et la croix de fermeture n'était plus accessible. Une vraie
    fenêtre Odoo a toujours sa croix et un bouton « Fermer »."""

    _name = "shopify.report.wizard"
    _description = "Rapport Shopify"

    title = fields.Char(string="Titre", readonly=True)
    kind = fields.Selection(
        [("info", "Info"), ("success", "Succès"), ("warning", "Attention"), ("danger", "Erreur")],
        default="info", readonly=True,
    )
    body_html = fields.Html(string="Rapport", readonly=True, sanitize=True)

    @api.model
    def open_report(self, title, message, kind="info"):
        lines = (message or "").split("\n")
        body = Markup("<br/>").join(escape(line) for line in lines)
        wizard = self.create({
            "title": title,
            "kind": kind if kind in ("info", "success", "warning", "danger") else "info",
            "body_html": Markup('<div class="o_shopify_report">%s</div>') % body,
        })
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(self.env.ref("shopify_odoo_connector.view_shopify_report_wizard_form").id, "form")],
            "target": "new",
        }
