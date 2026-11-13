# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = 'documents.document'

    def action_word_preview(self):
        """ Menu Action > Aperçu Word : ouvre le PDF du document Word
        sélectionné dans un nouvel onglet. """
        attachments = self.mapped('attachment_id').filtered(
            lambda a: a._word_preview_is_word())
        if not attachments:
            raise UserError(_("Sélectionnez un document Word (.docx, .doc, "
                              ".odt, .rtf)."))
        return attachments[:1].action_word_preview()

    def action_word_edit(self):
        """ Menu Action > Modifier dans Odoo (Word). """
        attachments = self.mapped('attachment_id').filtered(
            lambda a: a._word_preview_is_word())
        if not attachments:
            raise UserError(_("Sélectionnez un document Word (.docx, .doc, "
                              ".odt, .rtf)."))
        return attachments[:1].action_word_edit()
