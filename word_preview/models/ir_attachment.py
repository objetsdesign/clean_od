# -*- coding: utf-8 -*-
import hashlib
import os

from odoo import _, models
from odoo.exceptions import UserError

from .word_preview_cache import WORD_EXTENSIONS, WORD_MIMETYPES


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _word_preview_is_word(self):
        self.ensure_one()
        if self.type != 'binary':
            return False
        ext = os.path.splitext(self.name or '')[1].lower()
        return (self.mimetype or '') in WORD_MIMETYPES or ext in WORD_EXTENSIONS

    def _word_preview_get_pdf(self):
        """ PDF (bytes) de l'aperçu. À appeler APRÈS le contrôle d'accès. """
        self.ensure_one()
        if not self._word_preview_is_word():
            raise UserError(_("« %s » n'est pas un document Word.", self.name))
        attachment = self.sudo()
        checksum = attachment.checksum or hashlib.sha1(
            attachment.raw or b'').hexdigest()
        return self.env['word.preview.cache']._get_pdf(
            checksum, lambda: attachment.raw or b'', attachment.name)

    def _word_preview_url(self):
        self.ensure_one()
        return '/word_preview/%s/view' % self.id

    def action_word_preview(self):
        """ Ouvre l'aperçu PDF dans un nouvel onglet. """
        attachment = self.filtered(lambda a: a._word_preview_is_word())[:1]
        if not attachment:
            raise UserError(_("Sélectionnez un document Word (.docx, .doc, "
                              ".odt, .rtf)."))
        return {
            'type': 'ir.actions.act_url',
            'url': attachment._word_preview_url(),
            'target': 'new',
        }

    def action_word_edit(self):
        """ Ouvre le fichier Word dans l'éditeur Odoo. """
        attachment = self.filtered(lambda a: a._word_preview_is_word())[:1]
        if not attachment:
            raise UserError(_("Sélectionnez un document Word (.docx, .doc, "
                              ".odt, .rtf)."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/word_editor/sheet/%s' % attachment.id,
            'target': 'self',
        }
