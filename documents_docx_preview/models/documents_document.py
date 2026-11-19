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

    # Actions du menu « ⚙ Action » de Documents (anciennement word_preview_documents)
    def action_word_preview(self):
        """ Menu Action > Aperçu Word : ouvre l'aperçu du document Word
        sélectionné dans un nouvel onglet. """
        attachments = self.mapped('attachment_id').filtered(
            lambda a: a._word_preview_is_word())
        if not attachments:
            raise UserError("Sélectionnez un document Word (.docx, .doc, .odt, .rtf).")
        return attachments[:1].action_word_preview()

    def action_word_edit(self):
        """ Menu Action > Modifier dans Odoo (Word). """
        attachments = self.mapped('attachment_id').filtered(
            lambda a: a._word_preview_is_word())
        if not attachments:
            raise UserError("Sélectionnez un document Word (.docx, .doc, .odt, .rtf).")
        return attachments[:1].action_word_edit()
