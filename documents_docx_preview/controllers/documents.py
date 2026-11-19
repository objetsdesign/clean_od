from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request


class DocumentsWordClickController(http.Controller):

    @http.route("/docx_preview/open/<int:document_id>", type="http", auth="user", methods=["GET"])
    def open_document_in_word_editor(self, document_id, **kwargs):
        """Clic sur un Word dans Documents : vérifie les droits sur le document,
        puis ouvre l'éditeur Word de ce module."""
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
        return request.redirect("/word_editor/sheet/%s" % attachment.id)

    @http.route("/docx_preview/version", type="http", auth="user", methods=["GET"])
    def docx_preview_version(self, **kwargs):
        """Page de contrôle : version du module réellement installée en base."""
        module = request.env["ir.module.module"].sudo().search(
            [("name", "=", "documents_docx_preview")], limit=1
        )
        text = (
            "Clic Word dans Documents – module actif\n"
            f"Version installée (base de données) : {module.latest_version or '-'}\n"
            f"Version des fichiers sur le serveur : {module.installed_version or '-'}\n"
            f"État : {module.state or '-'}\n"
        )
        return request.make_response(text, headers=[("Content-Type", "text/plain; charset=utf-8")])
