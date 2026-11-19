import base64
import html
import json
import logging

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OOXML_EXTENSIONS = (".docx", ".docm", ".dotx")
MAX_SAVE_SIZE = 50 * 1024 * 1024  # 50 Mo

EDITOR_PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{name}</title>
<link rel="stylesheet" href="/documents_docx_preview/static/lib/superdoc/style.css"/>
<link rel="stylesheet" href="/documents_docx_preview/static/src/superdoc/editor.css"/>
</head><body>
<div id="sd-root" data-config="{config}">
  <header class="sd-bar">
    <span class="sd-logo">W</span>
    <span class="sd-name" title="{name}">{name}</span>
    <span id="sd-status" class="sd-status"></span>
    <span class="sd-spacer"></span>
    <button type="button" id="sd-save" class="sd-btn sd-primary" hidden>Enregistrer</button>
    <button type="button" id="sd-download" class="sd-btn">Télécharger</button>
    <button type="button" id="sd-close" class="sd-btn">Fermer</button>
  </header>
  <div id="sd-toolbar"></div>
  <div id="sd-message" class="sd-message">Ouverture du document…</div>
  <main id="sd-editor"></main>
</div>
<script src="/documents_docx_preview/static/lib/superdoc/superdoc.min.js"></script>
<script src="/documents_docx_preview/static/src/superdoc/editor.js"></script>
</body></html>
"""


def is_ooxml_document(document):
    name = (document.name or "").strip().lower()
    mimetype = document.mimetype or (document.attachment_id.mimetype if document.attachment_id else "")
    return mimetype == DOCX_MIMETYPE or name.endswith(OOXML_EXTENSIONS)


class SuperDocEditorController(http.Controller):

    def _get_document(self, document_id, operation="read"):
        document = request.env["documents.document"].browse(document_id).exists()
        if not document or not document.attachment_id:
            raise request.not_found()
        try:
            document.check_access(operation)
        except (AccessError, MissingError):
            raise request.not_found()
        if not is_ooxml_document(document):
            raise request.not_found()
        return document

    @staticmethod
    def _can_write(document):
        try:
            document.check_access("write")
            return True
        except (AccessError, MissingError):
            return False

    @http.route("/docx_preview/editor/<int:document_id>", type="http", auth="user", methods=["GET"])
    def superdoc_editor(self, document_id, **kwargs):
        """Éditeur Word (SuperDoc) pour un document .docx de Documents."""
        document = self._get_document(document_id)
        user = request.env.user
        config = {
            "documentId": document.id,
            "name": document.name or "document.docx",
            "contentUrl": f"/docx_preview/editor/{document.id}/content",
            "saveUrl": f"/docx_preview/editor/{document.id}/save",
            "canWrite": self._can_write(document),
            "csrfToken": request.csrf_token(),
            "user": {"name": user.name or "", "email": user.email or ""},
        }
        page = EDITOR_PAGE.format(
            name=html.escape(document.name or ""),
            config=html.escape(json.dumps(config), quote=True),
        )
        return request.make_response(page, headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ])

    @http.route("/docx_preview/editor/<int:document_id>/content", type="http", auth="user", methods=["GET"])
    def superdoc_content(self, document_id, **kwargs):
        """Contenu actuel du fichier .docx (droits de lecture vérifiés)."""
        document = self._get_document(document_id)
        data = document.sudo().attachment_id.raw or b""
        return request.make_response(data, headers=[
            ("Content-Type", DOCX_MIMETYPE),
            ("Content-Disposition", content_disposition(document.name or "document.docx", disposition_type="inline")),
            ("Cache-Control", "no-store"),
        ])

    @http.route("/docx_preview/editor/<int:document_id>/save", type="http", auth="user",
                methods=["POST"], csrf=True)
    def superdoc_save(self, document_id, file=None, **kwargs):
        """Enregistre le .docx modifié dans Documents (droits d'écriture vérifiés)."""
        def reply(payload, status=200):
            return request.make_response(json.dumps(payload), status=status,
                                         headers=[("Content-Type", "application/json")])

        document = self._get_document(document_id, operation="write")
        if file is None:
            return reply({"ok": False, "error": "Aucun fichier reçu."}, 400)
        data = file.read(MAX_SAVE_SIZE + 1)
        if len(data) > MAX_SAVE_SIZE:
            return reply({"ok": False, "error": "Fichier trop volumineux."}, 413)
        if not data.startswith(b"PK"):
            return reply({"ok": False, "error": "Le fichier reçu n'est pas un .docx valide."}, 400)
        if "datas" in document._fields:
            # Passe par Documents : l'ancienne version reste dans « Gérer les versions ».
            document.write({"datas": base64.b64encode(data)})
        else:
            document.sudo().attachment_id.write({"raw": data})
        _logger.info("Aperçu Word : document %s enregistré par l'utilisateur %s (%s octets)",
                     document.id, request.env.user.id, len(data))
        return reply({"ok": True})
