from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def od_project_ux_cleanup_menus(self):
        """Hide the native top-level 'Projects' and 'Tasks' menu tabs once
        this module provides its own 'Projets' (Portfolio) and 'Tâches'
        (Board) replacements, to avoid duplicate navigation.

        Native app tabs are sometimes a single menu with its own action,
        and sometimes a menu section with no action of its own whose
        children carry the action(s) - so this walks each top tab's whole
        subtree rather than assuming one shape. It only hides a tab when
        BOTH of these hold, to stay safe across Odoo point
        releases/editions and never touch unrelated tabs (Reporting,
        Configuration, ...):
          - its name (checked in English) is a known Projects/Tasks label
          - every action found anywhere in its subtree targets exactly
            that one model (project.project, resp. project.task) via a
            plain act_window - a mixed or reporting subtree is left alone

        Runs on every module install/upgrade (called from a <function>
        data record), not just on first install.
        """
        main_menu = self.env.ref("project.menu_main_pm", raise_if_not_found=False)
        if not main_menu:
            return

        our_action_tags = {"od_project_ux.board", "od_project_ux.portfolio"}
        our_menu_xmlids = [
            "od_project_ux.menu_project_ux_portfolio",
            "od_project_ux.menu_project_ux_board",
            "od_project_ux.menu_project_ux_my_tasks",
        ]
        our_menu_ids = set()
        for xmlid in our_menu_xmlids:
            ref = self.env.ref(xmlid, raise_if_not_found=False)
            if ref:
                our_menu_ids.add(ref.id)

        projects_labels = {"projects"}
        # We now ship our own guaranteed "Mes tâches" menu (see
        # views/project_my_tasks.xml), so the native "My Tasks" tab is a
        # duplicate too and gets hidden just like "Tasks"/"All Tasks".
        tasks_labels = {"tasks", "all tasks", "my tasks"}

        def subtree_models_and_flags(menu):
            models_found = set()
            has_other_client_action = False
            action = menu.action
            if action:
                if action._name == "ir.actions.act_window" and action.res_model:
                    models_found.add(action.res_model)
                elif action._name == "ir.actions.client":
                    if action.tag not in our_action_tags:
                        has_other_client_action = True
                    else:
                        has_other_client_action = has_other_client_action or False
            for child in menu.child_id:
                child_models, child_other = subtree_models_and_flags(child)
                models_found |= child_models
                has_other_client_action = has_other_client_action or child_other
            return models_found, has_other_client_action

        en_self = self.with_context(lang="en_US")
        top_menus = en_self.search([("parent_id", "=", main_menu.id)], order="id")
        # include inactive ones too, in case a previous version of this
        # cleanup over-hid something
        top_menus |= en_self.with_context(active_test=False).search(
            [("parent_id", "=", main_menu.id)]
        )

        for menu in top_menus:
            if menu.id in our_menu_ids:
                continue

            label = (menu.name or "").strip().lower()
            models_found, has_other_client_action = subtree_models_and_flags(menu)
            if has_other_client_action or not models_found:
                continue

            if label in projects_labels and models_found <= {"project.project"}:
                menu.write({"active": False})
            elif label in tasks_labels and models_found <= {"project.task"}:
                menu.write({"active": False})
