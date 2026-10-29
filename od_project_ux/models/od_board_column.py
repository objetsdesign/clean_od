import re

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


# Tables (Board / Portfolio) that support extra columns.
SUPPORTED_MODELS = [
    ("project.project", "Projets"),
    ("project.task", "Tâches"),
]

# Field types that can be shown (and, unless readonly, edited) in a table
# cell. Binary / html / json / properties / one2many are left out on
# purpose: they don't fit in a single table cell.
SUPPORTED_TYPES = {
    "char", "text", "integer", "float", "monetary", "boolean",
    "date", "datetime", "selection", "many2one", "many2many",
}

# Columns the tables already render natively - not offered again.
NATIVE_COLUMNS = {
    "project.project": {
        "name", "user_id", "last_update_status", "board_priority",
        "board_status", "date_start", "date",
    },
    "project.task": {
        "name", "state", "priority", "tag_ids", "user_ids",
        "od_date_start", "date_deadline", "stage_id",
    },
}

# Technical / noisy fields never worth a column.
EXCLUDED_FIELDS = {
    "id", "display_name", "create_uid", "write_uid", "__last_update",
    "access_token", "access_url", "access_warning", "sequence",
    "color", "board_color", "rating_ids", "rating_last_value",
    "privacy_visibility_warning", "last_update_color", "link_preview_name",
    "displayed_image_id", "personal_stage_type_id", "personal_stage_type_ids",
    "personal_stage_id", "portal_user_names", "recurrence_id",
    "is_milestone_exceeded", "is_milestone_deadline_exceeded",
    "has_late_and_unreached_milestone",
}
EXCLUDED_PREFIXES = (
    "message_", "activity_", "website_message", "has_message",
    "rating_", "access_", "alias_", "__", "display_", "show_", "can_",
    "current_user", "my_activity",
)

PERCENT_HINT = re.compile(r"(percent|progress|completion|avancement)", re.I)


class OdBoardColumn(models.Model):
    _name = "od.board.column"
    _description = "Project UX - extra table column"
    _order = "res_model, sequence, id"

    res_model = fields.Selection(SUPPORTED_MODELS, required=True, index=True)
    field_name = fields.Char(required=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ("od_board_column_unique", "unique(res_model, field_name)",
         "This field is already a column of this table."),
    ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_model(self, res_model):
        if res_model not in dict(SUPPORTED_MODELS):
            raise UserError(_("Unsupported table: %s", res_model))

    def _can_manage(self):
        return self.env.user.has_group("project.group_project_manager")

    def _is_offered(self, res_model, fname, desc):
        if desc.get("type") not in SUPPORTED_TYPES:
            return False
        if fname in EXCLUDED_FIELDS or fname in NATIVE_COLUMNS[res_model]:
            return False
        if fname.startswith(EXCLUDED_PREFIXES):
            return False
        return True

    def _percent_scale(self, res_model, fname, ftype):
        """Return 'ratio' (value stored as 0..1, e.g. widget=percentage),
        'pct' (value stored as 0..100, e.g. widget=progressbar) or False
        when the field is not a percentage. Detected from the widget used
        in the model's own form/list views, falling back to the name."""
        if ftype not in ("float", "integer"):
            return False
        Model = self.env[res_model]
        pattern = re.compile(
            r'<field[^>]*name="%s"[^>]*widget="(percentage|progressbar|percentpie)"'
            r'|<field[^>]*widget="(percentage|progressbar|percentpie)"[^>]*name="%s"'
            % (re.escape(fname), re.escape(fname))
        )
        for view_type in ("form", "list"):
            try:
                arch = Model.get_view(view_type=view_type)["arch"]
            except Exception:  # noqa: BLE001 - a missing view is not an error here
                continue
            match = pattern.search(arch)
            if match:
                widget = match.group(1) or match.group(2)
                return "ratio" if widget == "percentage" else "pct"
        return "pct" if PERCENT_HINT.search(fname) else False

    def _column_info(self, res_model, fname, desc, column_id=False):
        return {
            "id": column_id,
            "name": fname,
            "label": desc.get("string") or fname,
            "type": desc.get("type"),
            "readonly": bool(desc.get("readonly")),
            "relation": desc.get("relation") or False,
            "selection": desc.get("selection") or [],
            "percent": self._percent_scale(res_model, fname, desc.get("type")),
            "help": desc.get("help") or "",
        }

    def _fields_desc(self, res_model):
        # fields_get already hides fields the user has no access to
        # (groups=...), so nothing restricted is ever offered.
        return self.env[res_model].fields_get(
            attributes=["string", "type", "readonly", "relation",
                        "selection", "help", "store"]
        )

    # ------------------------------------------------------------------
    # Column configuration (called from the OWL tables)
    # ------------------------------------------------------------------
    @api.model
    def od_get_columns(self, res_model):
        self._check_model(res_model)
        desc = self._fields_desc(res_model)
        columns = []
        for col in self.sudo().search([("res_model", "=", res_model)]):
            if col.field_name in desc:
                columns.append(self._column_info(
                    res_model, col.field_name, desc[col.field_name], col.id
                ))
        return {"columns": columns, "can_manage": self._can_manage()}

    @api.model
    def od_get_available_fields(self, res_model):
        self._check_model(res_model)
        desc = self._fields_desc(res_model)
        used = set(self.sudo().search([("res_model", "=", res_model)]).mapped("field_name"))
        result = []
        for fname, fdesc in desc.items():
            if fname in used or not self._is_offered(res_model, fname, fdesc):
                continue
            result.append({
                "name": fname,
                "label": fdesc.get("string") or fname,
                "type": fdesc["type"],
                "readonly": bool(fdesc.get("readonly")),
            })
        result.sort(key=lambda f: f["label"].lower())
        return result

    @api.model
    def od_add_column(self, res_model, field_name):
        self._check_model(res_model)
        if not self._can_manage():
            raise AccessError(_("Only project managers can add columns."))
        desc = self._fields_desc(res_model)
        if field_name not in desc or not self._is_offered(res_model, field_name, desc[field_name]):
            raise UserError(_("This field cannot be added as a column."))
        last = self.sudo().search([("res_model", "=", res_model)], order="sequence desc", limit=1)
        col = self.sudo().create({
            "res_model": res_model,
            "field_name": field_name,
            "sequence": (last.sequence + 1) if last else 1,
        })
        return self._column_info(res_model, field_name, desc[field_name], col.id)

    @api.model
    def od_remove_column(self, column_id):
        if not self._can_manage():
            raise AccessError(_("Only project managers can remove columns."))
        self.sudo().browse(column_id).unlink()
        return True

    # ------------------------------------------------------------------
    # Values
    # ------------------------------------------------------------------
    def _user_tz(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "UTC")

    def _format_value(self, record, fname, desc, percent):
        ftype = desc["type"]
        value = record[fname]
        if ftype == "many2one":
            return {"value": value.id or False, "display": value.display_name or ""}
        if ftype == "many2many":
            return {
                "value": value.ids,
                "display": [{"id": r.id, "name": r.display_name} for r in value[:20]],
            }
        if ftype == "selection":
            return {"value": value or False, "display": dict(desc.get("selection") or []).get(value, "")}
        if ftype == "date":
            return {"value": value and value.isoformat() or False, "display": ""}
        if ftype == "datetime":
            if not value:
                return {"value": False, "display": ""}
            local = pytz.utc.localize(value).astimezone(self._user_tz())
            return {"value": local.strftime("%Y-%m-%dT%H:%M"), "display": ""}
        if ftype == "boolean":
            return {"value": bool(value), "display": ""}
        if ftype in ("integer", "float", "monetary"):
            out = {"value": value or 0, "display": ""}
            if percent:
                pct = (value or 0) * 100 if percent == "ratio" else (value or 0)
                out["pct"] = round(pct, 1)
            if ftype == "monetary":
                cur_field = desc.get("currency_field") or "currency_id"
                currency = record[cur_field] if cur_field in record._fields else False
                out["currency"] = currency and currency.symbol or ""
            return out
        return {"value": value or "", "display": ""}

    @api.model
    def od_read_values(self, res_model, record_ids, field_names=None):
        """Return {record_id: {field_name: {value, display, ...}}} for the
        configured extra columns of this table."""
        self._check_model(res_model)
        cols = self.sudo().search([("res_model", "=", res_model)])
        names = [c.field_name for c in cols if not field_names or c.field_name in field_names]
        Model = self.env[res_model]
        all_desc = Model.fields_get(attributes=["type", "selection", "currency_field"])
        names = [n for n in names if n in all_desc]
        if not names or not record_ids:
            return {}
        percents = {
            n: self._percent_scale(res_model, n, all_desc[n]["type"]) for n in names
        }
        result = {}
        for record in Model.browse(record_ids).exists():
            result[record.id] = {
                n: self._format_value(record, n, all_desc[n], percents[n]) for n in names
            }
        return result

    @api.model
    def od_write_value(self, res_model, record_id, field_name, value):
        """Write one cell. Only fields configured as a column of this table
        are writable through here, with the user's own access rights."""
        self._check_model(res_model)
        if not self.sudo().search_count([("res_model", "=", res_model), ("field_name", "=", field_name)]):
            raise UserError(_("This field is not a column of this table."))
        Model = self.env[res_model]
        desc = Model.fields_get([field_name], attributes=["type", "readonly", "selection"])[field_name]
        if desc.get("readonly"):
            raise UserError(_("This field is read-only."))
        ftype = desc["type"]

        if value in (None, "") and ftype not in ("char", "text"):
            value = False
        if ftype == "many2one":
            value = int(value) if value else False
        elif ftype == "many2many":
            value = [(6, 0, [int(v) for v in (value or [])])]
        elif ftype == "boolean":
            value = bool(value)
        elif ftype == "integer":
            value = int(float(value)) if value not in (False, None) else 0
        elif ftype in ("float", "monetary"):
            value = float(value) if value not in (False, None) else 0.0
            if self._percent_scale(res_model, field_name, ftype) == "ratio":
                value = value / 100.0
        elif ftype == "datetime" and value:
            local = self._user_tz().localize(
                fields.Datetime.to_datetime(value.replace("T", " ")[:16] + ":00")
            )
            value = fields.Datetime.to_string(local.astimezone(pytz.utc).replace(tzinfo=None))

        Model.browse(record_id).write({field_name: value})
        return self.od_read_values(res_model, [record_id], [field_name]).get(record_id, {}).get(field_name)
