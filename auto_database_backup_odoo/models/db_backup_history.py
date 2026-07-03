from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import os


class DbBackupHistory(models.Model):
    _name = "db.backup.history"
    _description = "Database Backup History"
    _order = "backup_date desc"

    name = fields.Char("File Name", required=True)
    backup_path = fields.Char("Backup Path")
    backup_date = fields.Datetime("Backup Date", default=fields.Datetime.now)
    backup_file = fields.Binary("Backup File", readonly=True)
    file_size = fields.Char("File Size", compute="_compute_file_size", store=True)
    backup_path = fields.Char(string="Backup Path", required=True) 

    @api.depends("backup_file")
    def _compute_file_size(self):
        for rec in self:
            if rec.backup_file:
                rec.file_size = str(round(len(rec.backup_file) / 1024 / 1024, 2)) + " MB"
            else:
                rec.file_size = "0 MB"

    def action_download_file(self):
        """Return file as attachment to download"""
        self.ensure_one()
        if not self.backup_file:
            raise UserError(_("File not found in record"))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/backup_file/{self.name}?download=true",
            "target": "self",
        }

    def action_delete_file(self):
        """Delete file from both FS and record"""
        self.ensure_one()
        if self.backup_path and os.path.exists(self.backup_path):
            try:
                os.remove(self.backup_path)
            except Exception:
                pass
        self.unlink()
