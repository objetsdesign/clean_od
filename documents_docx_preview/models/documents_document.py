from odoo import models
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def action_docx_preview(self):
        """Bouton « Aperçu » : ouvre le fichier Word dans l'éditeur Word
        (même écran que « Action > Modifier dans Odoo (Word) »)."""
        word_docs = self.filtered(
            lambda d: d.attachment_id and d.attachment_id._word_preview_is_word()
        )
        if not word_docs:
            raise UserError("Sélectionnez un fichier Word (.docx, .doc, .odt, .rtf).")
        return {
            "type": "ir.actions.act_url",
            "url": "/docx_preview/open/%s" % word_docs[0].id,
            "target": "new",
        }
