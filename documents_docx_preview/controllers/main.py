import html
import json
import logging
import re
import time
from urllib.parse import quote

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request
from odoo.tools import consteq
from odoo.tools.misc import hmac as odoo_hmac

_logger = logging.getLogger(__name__)

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
VIEWER_PATH = "/documents_docx_preview/static/src/viewer/docx_viewer.html"
HMAC_SCOPE = "documents_docx_preview.word"
WORD_LINK_TTL = 30 * 60  # durée de validité du lien signé pour Word (secondes)


def _sign(document_id, expiry):
    return odoo_hmac(request.env(su=True), HMAC_SCOPE, f"{document_id}:{expiry}")


def _safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|#%]+', "_", (name or "document").strip()) or "document"
    if not name.lower().endswith(".docx"):
        name += ".docx"
    return name


OPEN_WORD_PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ouverture dans Word – {name}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f3f2f1;color:#323130}}
header{{background:#2b579a;color:#fff;padding:14px 24px;font-size:18px;font-weight:600}}
main{{max-width:560px;margin:48px auto;background:#fff;border-radius:8px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,.12)}}
h1{{font-size:20px;margin:0 0 8px}} p{{line-height:1.5}}
.btn{{display:inline-block;padding:10px 18px;border-radius:4px;text-decoration:none;font-weight:600;margin:8px 8px 0 0}}
.primary{{background:#2b579a;color:#fff}} .secondary{{background:#edebe9;color:#323130}}
small{{color:#605e5c}}
</style></head>
<body>
<header>Microsoft Word</header>
<main>
<h1>{name}</h1>
<p>Word va s'ouvrir sur votre ordinateur. Si votre navigateur demande
l'autorisation d'ouvrir <b>Microsoft Word</b>, cliquez sur <b>Ouvrir</b>.</p>
<a class="btn primary" href="{word_uri}">Ouvrir dans Word</a>
<a class="btn secondary" href="{download_url}">Télécharger</a>
<p><small>Le fichier s'ouvre en lecture seule depuis Odoo. Pour garder des modifications,
utilisez « Fichier → Enregistrer sous » dans Word, puis réimportez le fichier dans Documents.
Vous pouvez fermer cet onglet une fois Word ouvert.</small></p>
</main>
<script>window.location.href = {word_uri_js};</script>
</body></html>
"""


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

    @http.route("/docx_preview/<int:document_id>/word", type="http", auth="user", methods=["GET"])
    def docx_open_word(self, document_id, **kwargs):
        """Page qui lance Microsoft Word (protocole ms-word:) sur un lien signé."""
        document = self._get_document(document_id)
        expiry = int(time.time()) + WORD_LINK_TTL
        token = _sign(document.id, expiry)
        filename = quote(_safe_filename(document.name))
        base_url = document.get_base_url().rstrip("/")
        file_url = f"{base_url}/docx_preview/word/{document.id}/{expiry}/{token}/{filename}"
        word_uri = f"ms-word:ofv|u|{file_url}"
        page = OPEN_WORD_PAGE.format(
            name=html.escape(document.name or ""),
            word_uri=html.escape(word_uri, quote=True),
            word_uri_js=json.dumps(word_uri).replace("</", "<\\/"),
            download_url=html.escape(f"/docx_preview/{document.id}/content?download=1", quote=True),
        )
        return request.make_response(page, headers=[("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")])

    @http.route(
        "/docx_preview/word/<int:document_id>/<int:expiry>/<string:token>/<path:filename>",
        type="http", auth="public", methods=["GET", "HEAD", "OPTIONS"], csrf=False, save_session=False,
    )
    def docx_word_file(self, document_id, expiry, token, filename=None, **kwargs):
        """Fichier servi à Microsoft Word (qui n'a pas la session Odoo du navigateur).
        Accès uniquement avec un lien signé, valable WORD_LINK_TTL secondes."""
        if expiry < time.time() or not consteq(token, _sign(document_id, expiry)):
            raise NotFound()
        document = request.env["documents.document"].sudo().browse(document_id).exists()
        if not document or not _is_docx(document) or not document.attachment_id:
            raise NotFound()
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[("Allow", "GET, HEAD, OPTIONS")])
        data = document.attachment_id.raw or b""
        headers = [
            ("Content-Type", DOCX_MIMETYPE),
            ("Content-Disposition", content_disposition(_safe_filename(document.name), disposition_type="inline")),
            ("Cache-Control", "no-store"),
        ]
        # Pour une requête HEAD, werkzeug n'envoie que les en-têtes.
        return request.make_response(data, headers=headers)

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
