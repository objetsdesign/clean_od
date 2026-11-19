from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from .collabora import collabora_url


class DocumentsWordClickController(http.Controller):

    @http.route("/docx_preview/open/<int:document_id>", type="http", auth="user", methods=["GET"])
    def open_document_in_word_editor(self, document_id, **kwargs):
        """Clic sur un Word dans Documents : vérifie les droits sur le document,
        puis ouvre Collabora Online s'il est configuré, sinon l'éditeur Word
        (LibreOffice)."""
        document = request.env["documents.document"].browse(document_id).exists()
        if not document:
            raise request.not_found()
        try:
            document.check_access("read")
        except (AccessError, MissingError):
            raise request.not_found()
        attachment = document.attachment_id
        if not attachment or not attachment._word_preview_is_word():
            raise request.not_found()
        target = collabora_url(document)
        if target:
            return request.redirect(target)
        return request.redirect("/word_editor/sheet/%s" % attachment.id)
