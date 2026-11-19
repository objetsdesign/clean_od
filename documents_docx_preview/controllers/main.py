import logging
from urllib.parse import quote

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
VIEWER_PATH = "/documents_docx_preview/static/src/viewer/docx_viewer.html"


def _is_docx(document):
    name = (document.name or "").strip().lower()
    return document.mimetype == DOCX_MIMETYPE or name.endswith(".docx")


def _check_read_access(record):
    """Vérifie que l'utilisateur connecté peut lire l'enregistrement."""
    if hasattr(record, "check_access"):  # Odoo 18+
        record.check_access("read")
    else:  # versions antérieures
        record.check_access_rights("read")
        record.check_access_rule("read")


class DocxPreviewController(http.Controller):

    @http.route("/docx_preview/version", type="http", auth="user", methods=["GET"])
    def docx_preview_version(self, **kwargs):
        """Page de contrôle : version du module réellement installée en base."""
        module = request.env["ir.module.module"].sudo().search(
            [("name", "=", "documents_docx_preview")], limit=1
        )
        text = (
            "Aperçu Word – module actif\n"
            f"Version installée (base de données) : {module.latest_version or '-'}\n"
            f"Version des fichiers sur le serveur : {module.installed_version or '-'}\n"
            f"État : {module.state or '-'}\n"
        )
        return request.make_response(text, headers=[("Content-Type", "text/plain; charset=utf-8")])

    def _get_document(self, document_id):
        document = request.env["documents.document"].browse(document_id).exists()
        if not document:
            raise NotFound()
        try:
            _check_read_access(document)
        except AccessError:
            raise NotFound()
        if not _is_docx(document):
            raise UserError("Ce document n'est pas un fichier Word (.docx).")
        return document

    @http.route("/docx_preview/<int:document_id>", type="http", auth="user", methods=["GET"])
    def docx_preview_page(self, document_id, **kwargs):
        """Page d'aperçu : redirige vers la visionneuse avec le lien du contenu."""
        document = self._get_document(document_id)
        content_url = f"/docx_preview/{document.id}/content"
        return request.redirect(
            f"{VIEWER_PATH}?file={quote(content_url, safe='')}&name={quote(document.name or '', safe='')}",
            local=True,
        )

    @http.route("/docx_preview/<int:document_id>/content", type="http", auth="user", methods=["GET"])
    def docx_preview_content(self, document_id, download=None, **kwargs):
        """Renvoie le contenu binaire du .docx, après contrôle des droits."""
        document = self._get_document(document_id)
        # Les droits ont été vérifiés sur le document : lecture de la pièce jointe en sudo.
        attachment = document.sudo().attachment_id
        data = attachment.raw if attachment else False
        if not data:
            _logger.warning("Aperçu Word : document %s sans contenu", document.id)
            raise NotFound()
        filename = document.name or "document.docx"
        disposition = "attachment" if download else "inline"
        headers = [
            ("Content-Type", DOCX_MIMETYPE),
            ("Content-Length", str(len(data))),
            ("Content-Disposition", content_disposition(filename, disposition_type=disposition)),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        return request.make_response(data, headers=headers)
