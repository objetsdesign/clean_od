import html
import json
import os
from urllib.parse import quote

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import content_disposition, request

PDFJS_VIEWER = "/web/static/lib/pdfjs/web/viewer.html"

SLIDES_PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{name}</title>
<link rel="stylesheet" href="/documents_docx_preview/static/src/slides/slides.css"/>
</head><body>
<div id="sv-root" data-config="{config}">
  <header class="sv-bar">
    <span class="sv-logo">P</span>
    <span class="sv-name" title="{name}">{name}</span>
    <span id="sv-status" class="sv-status"></span>
    <span class="sv-spacer"></span>
    <button type="button" id="sv-present" class="sv-btn sv-primary" hidden>Diaporama</button>
    <a id="sv-download" class="sv-btn" href="{download_url}">Télécharger</a>
    <button type="button" id="sv-close" class="sv-btn">Fermer</button>
  </header>
  <div id="sv-message" class="sv-message"><div class="sv-spinner"></div>Préparation des diapositives…</div>
  <iframe id="sv-viewer" title="Diapositives" hidden="hidden"></iframe>
</div>
<script src="/documents_docx_preview/static/src/slides/slides.js"></script>
</body></html>
"""


class SlidesPreviewController(http.Controller):

    def _get_document(self, document_id):
        document = request.env["documents.document"].browse(document_id).exists()
        if not document or not document.attachment_id:
            raise request.not_found()
        try:
            document.check_access("read")
        except (AccessError, MissingError):
            raise request.not_found()
        if not document.attachment_id._slides_preview_is_slides():
            raise request.not_found()
        return document

    @http.route("/slides_preview/<int:document_id>", type="http", auth="user", methods=["GET"])
    def slides_page(self, document_id, **kwargs):
        """Visionneuse de diapositives pour une présentation de Documents."""
        document = self._get_document(document_id)
        pdf_url = f"/slides_preview/{document.id}/pdf"
        config = {
            "name": document.name or "presentation",
            "pdfUrl": pdf_url,
            "viewerUrl": f"{PDFJS_VIEWER}?file={quote(pdf_url, safe='')}#pagemode=none&zoom=page-fit",
        }
        page = SLIDES_PAGE.format(
            name=html.escape(document.name or ""),
            config=html.escape(json.dumps(config), quote=True),
            download_url=html.escape(f"/slides_preview/{document.id}/download", quote=True),
        )
        return request.make_response(page, headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ])

    @http.route("/slides_preview/<int:document_id>/pdf", type="http", auth="user", methods=["GET"])
    def slides_pdf(self, document_id, **kwargs):
        """Diapositives converties en PDF par LibreOffice (mises en cache)."""
        document = self._get_document(document_id)
        try:
            pdf = document.attachment_id._slides_preview_get_pdf()
        except UserError as error:
            return request.make_response(
                error.args[0], status=422,
                headers=[("Content-Type", "text/plain; charset=utf-8")])
        filename = os.path.splitext(document.name or "presentation")[0] + ".pdf"
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Disposition", content_disposition(filename, "inline")),
            ("Cache-Control", "private, max-age=3600"),
            ("X-Content-Type-Options", "nosniff"),
        ])

    @http.route("/slides_preview/<int:document_id>/download", type="http", auth="user", methods=["GET"])
    def slides_download(self, document_id, **kwargs):
        """Fichier PowerPoint d'origine."""
        document = self._get_document(document_id)
        attachment = document.sudo().attachment_id
        return request.make_response(attachment.raw or b"", headers=[
            ("Content-Type", attachment.mimetype or "application/octet-stream"),
            ("Content-Disposition", content_disposition(document.name or "presentation.pptx")),
            ("Cache-Control", "no-store"),
        ])
