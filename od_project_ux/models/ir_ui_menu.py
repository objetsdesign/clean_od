from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def od_project_ux_cleanup_menus(self):
        """Hide the native top-level 'Projects' and 'Tasks' menu entries
        once this module provides its own 'Projets' (Portfolio) and
        'Tâches' (Board) replacements, to avoid duplicate navigation.

        Looks the menus up by the model their action targets rather than
        by a hardcoded external id, so it keeps working across Odoo
        point releases/editions that may name those menus differently.
        Runs on every module install/upgrade (called from a <function>
        data record), not just on first install.
        """
        main_menu = self.env.ref("project.menu_main_pm", raise_if_not_found=False)
        if not main_menu:
            return

        our_action_tags = {"od_project_ux.board", "od_project_ux.portfolio"}

        for menu in self.search([("parent_id", "=", main_menu.id)]):
            action = menu.action
            if not action:
                continue
            if action._name == "ir.actions.client" and action.tag in our_action_tags:
                continue
            if action._name == "ir.actions.act_window" and action.res_model in (
                "project.project", "project.task"
            ):
                menu.write({"active": False})
