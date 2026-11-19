from odoo import models
from odoo.exceptions import UserError

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def _is_docx_preview(self):
        self.ensure_one()
        name = (self.name or "").strip().lower()
        return self.mimetype == DOCX_MIMETYPE or name.endswith(".docx")

    def action_docx_preview(self):
        """Ouvre l'aperçu Word du document dans un nouvel onglet."""
        docx = self.filtered(lambda d: d._is_docx_preview())
        if not docx:
            raise UserError("Sélectionnez un fichier Word (.docx) pour afficher son aperçu.")
        return {
            "type": "ir.actions.act_url",
            "url": "/docx_preview/%s" % docx[0].id,
            "target": "new",
        }

    def action_docx_open_word(self):
        """Ouvre le document dans Microsoft Word installé sur l'ordinateur."""
        docx = self.filtered(lambda d: d._is_docx_preview())
        if not docx:
            raise UserError("Sélectionnez un fichier Word (.docx) à ouvrir dans Word.")
        return {
            "type": "ir.actions.act_url",
            "url": "/docx_preview/%s/word" % docx[0].id,
            "target": "new",
        }
