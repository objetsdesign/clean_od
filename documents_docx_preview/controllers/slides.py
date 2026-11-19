import base64
import html
import json
import logging
import os
from urllib.parse import quote

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import content_disposition, request

from ..models.pptx_text import PptxTextError, apply_changes, read_slides
from .collabora import collabora_url

_logger = logging.getLogger(__name__)

PDFJS_VIEWER = "/web/static/lib/pdfjs/web/viewer.html"
# Formats PowerPoint « XML » dont les textes sont modifiables.
EDITABLE_EXTENSIONS = (".pptx", ".pptm", ".ppsx", ".potx")
MAX_SAVE_PAYLOAD = 2 * 1024 * 1024  # 2 Mo de textes au maximum

EDITOR_PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{name}</title>
<link rel="stylesheet" href="/documents_docx_preview/static/src/slides/slides.css"/>
<link rel="stylesheet" href="/documents_docx_preview/static/src/slides/slides_editor.css"/>
</head><body>
<div id="se-root" data-config="{config}">
  <header class="sv-bar">
    <span class="sv-logo">P</span>
    <span class="sv-name" title="{name}">{name}</span>
    <span id="se-status" class="sv-status"></span>
    <span class="sv-spacer"></span>
    <button type="button" id="se-save" class="sv-btn sv-primary" disabled="disabled">Enregistrer</button>
    <a id="se-preview" class="sv-btn" href="{preview_url}">Aperçu</a>
    <button type="button" id="se-close" class="sv-btn">Fermer</button>
  </header>
  <div id="se-message" class="sv-message"><div class="sv-spinner"></div>Chargement des diapositives…</div>
  <main id="se-slides"></main>
</div>
<script type="module" src="/documents_docx_preview/static/src/slides/slides_editor.js"></script>
</body></html>
"""

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
    {edit_button}
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

    @staticmethod
    def _can_write(document):
        try:
            document.check_access("write")
            return True
        except (AccessError, MissingError):
            return False

    @staticmethod
    def _is_editable_format(document):
        name = (document.name or "").strip().lower()
        return name.endswith(EDITABLE_EXTENSIONS) or (document.attachment_id.mimetype or "").startswith(
            "application/vnd.openxmlformats-officedocument.presentationml")

    @http.route("/slides_preview/<int:document_id>", type="http", auth="user", methods=["GET"])
    def slides_page(self, document_id, **kwargs):
        """Visionneuse de diapositives pour une présentation de Documents."""
        document = self._get_document(document_id)
        # Collabora Online configuré : édition complète (couleurs, animations…).
        target = collabora_url(document)
        if target and not kwargs.get("viewer"):
            return request.redirect(target)
        # La version (empreinte) dans l'adresse évite d'afficher un ancien PDF en cache.
        pdf_url = f"/slides_preview/{document.id}/pdf?v={document.sudo().attachment_id.checksum or ''}"
        config = {
            "name": document.name or "presentation",
            "pdfUrl": pdf_url,
            "viewerUrl": f"{PDFJS_VIEWER}?file={quote(pdf_url, safe='')}#pagemode=none&zoom=page-fit",
        }
        edit_button = ""
        if self._is_editable_format(document) and self._can_write(document):
            edit_button = (f'<a id="sv-edit" class="sv-btn" href="/slides_editor/{document.id}">'
                           "Modifier les textes</a>")
        page = SLIDES_PAGE.format(
            name=html.escape(document.name or ""),
            config=html.escape(json.dumps(config), quote=True),
            download_url=html.escape(f"/slides_preview/{document.id}/download", quote=True),
            edit_button=edit_button,
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

    # ------------------------------------------------------------------
    # Éditeur simple : modification des textes des diapositives
    # ------------------------------------------------------------------
    def _get_editable_document(self, document_id, operation="read"):
        document = self._get_document(document_id)
        if not self._is_editable_format(document):
            raise request.not_found()
        if operation == "write" and not self._can_write(document):
            raise request.not_found()
        return document

    @http.route("/slides_editor/<int:document_id>", type="http", auth="user", methods=["GET"])
    def slides_editor_page(self, document_id, **kwargs):
        document = self._get_editable_document(document_id, operation="write")
        config = {
            "name": document.name or "presentation.pptx",
            "dataUrl": f"/slides_editor/{document.id}/data",
            "saveUrl": f"/slides_editor/{document.id}/save",
            "pdfUrl": f"/slides_preview/{document.id}/pdf",
            "csrfToken": request.csrf_token(),
        }
        page = EDITOR_PAGE.format(
            name=html.escape(document.name or ""),
            config=html.escape(json.dumps(config), quote=True),
            preview_url=html.escape(f"/slides_preview/{document.id}", quote=True),
        )
        return request.make_response(page, headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ])

    @http.route("/slides_editor/<int:document_id>/data", type="http", auth="user", methods=["GET"])
    def slides_editor_data(self, document_id, **kwargs):
        document = self._get_editable_document(document_id, operation="write")
        attachment = document.sudo().attachment_id
        try:
            slides = read_slides(attachment.raw or b"")
        except (PptxTextError, ValueError) as error:
            return self._json({"ok": False, "error": str(error)}, 422)
        return self._json({"ok": True, "checksum": attachment.checksum, "slides": slides})

    @http.route("/slides_editor/<int:document_id>/save", type="http", auth="user",
                methods=["POST"], csrf=True)
    def slides_editor_save(self, document_id, payload=None, **kwargs):
        document = self._get_editable_document(document_id, operation="write")
        if not payload or len(payload) > MAX_SAVE_PAYLOAD:
            return self._json({"ok": False, "error": "Modifications manquantes ou trop volumineuses."}, 400)
        try:
            values = json.loads(payload)
            changes = values["changes"]
            if not isinstance(changes, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self._json({"ok": False, "error": "Requête invalide."}, 400)
        attachment = document.sudo().attachment_id
        if values.get("checksum") != attachment.checksum:
            return self._json({"ok": False, "error": (
                "Le fichier a été modifié entre-temps. Rechargez la page pour "
                "repartir de la dernière version.")}, 409)
        try:
            data = apply_changes(attachment.raw or b"", changes)
        except (PptxTextError, ValueError) as error:
            return self._json({"ok": False, "error": str(error)}, 422)
        if "datas" in document._fields:
            # Passe par Documents : l'ancienne version reste dans « Gérer les versions ».
            document.write({"datas": base64.b64encode(data)})
        else:
            attachment.write({"raw": data})
        _logger.info("Aperçu PowerPoint : textes du document %s modifiés par l'utilisateur %s",
                     document.id, request.env.user.id)
        return self._json({"ok": True, "checksum": document.sudo().attachment_id.checksum})

    @staticmethod
    def _json(payload, status=200):
        return request.make_response(json.dumps(payload), status=status, headers=[
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-store"),
        ])
