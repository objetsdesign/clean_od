# -*- coding: utf-8 -*-
import logging
import os

from urllib.parse import urlencode

from markupsafe import escape

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import content_disposition, request

OOXML_EXTENSIONS = ('.docx', '.docm', '.dotx')

VIEWER_HTML = '''<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{name}</title>
<link rel="stylesheet" href="/word_preview/static/src/viewer/word_viewer.css"/>
</head><body>
<div id="wv-root" data-mode="{mode}" data-content-url="{content_url}" data-pdf-url="{pdf_url}">
  <div class="wv-bar">
    <span class="wv-icon">W</span>
    <span class="wv-name" title="{name}">{name}</span>
    <span id="wv-zoom-box">
      <button type="button" id="wv-zoom-out" title="Zoom arri\u00e8re">&#8722;</button>
      <span class="wv-zoom" id="wv-zoom-value">100%</span>
      <button type="button" id="wv-zoom-in" title="Zoom avant">+</button>
    </span>
    {edit_button}
    <button type="button" id="wv-print">Imprimer</button>
    <a href="{download_url}">T\u00e9l\u00e9charger</a>
  </div>
  <div id="wv-message" class="wv-message"><div class="wv-spinner"></div>Ouverture du document\u2026</div>
  <div id="wv-doc"></div>
  <iframe id="wv-pdf" title="Aper\u00e7u"></iframe>
</div>
<script src="/word_preview/static/lib/jszip.min.js"></script>
<script src="/word_preview/static/lib/docx-preview.min.js"></script>
<script src="/word_preview/static/src/viewer/word_viewer.js"></script>
</body></html>'''

_logger = logging.getLogger(__name__)


class WordPreviewController(http.Controller):

    @http.route('/word_preview/<int:attachment_id>', type='http',
                auth='public', methods=['GET'])
    def word_preview(self, attachment_id, access_token=None, **kwargs):
        """ Retourne le document Word converti en PDF, affiché « inline ».
        Les droits sont ceux de /web/content : l'utilisateur doit pouvoir
        lire la pièce jointe (ou fournir un jeton d'accès valide). """
        try:
            attachment = request.env['ir.binary']._find_record(
                res_model='ir.attachment', res_id=attachment_id,
                access_token=access_token)
        except (MissingError, AccessError):
            raise request.not_found()
        if not attachment._word_preview_is_word():
            raise request.not_found()
        try:
            pdf = attachment._word_preview_get_pdf()
        except UserError as error:
            return request.make_response(
                '<html><body style="font-family:sans-serif;padding:2em">'
                '<h3>Aperçu indisponible</h3><p>%s</p></body></html>'
                % escape(error.args[0]),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
                status=422)
        filename = os.path.splitext(attachment.name or 'document')[0] + '.pdf'
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', content_disposition(filename, 'inline')),
            ('Cache-Control', 'private, max-age=3600'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/word_preview/<int:attachment_id>/view', type='http',
                auth='public', methods=['GET'])
    def word_preview_view(self, attachment_id, access_token=None, **kwargs):
        """ Page d'aperçu « façon Word » : le .docx est rendu en pages dans
        le navigateur (docx-preview). Les anciens formats (.doc, .odt, .rtf)
        sont affichés via la conversion PDF. """
        try:
            attachment = request.env['ir.binary']._find_record(
                res_model='ir.attachment', res_id=attachment_id,
                access_token=access_token)
        except (MissingError, AccessError):
            raise request.not_found()
        if not attachment._word_preview_is_word():
            raise request.not_found()
        token = {'access_token': access_token} if access_token else {}
        name = attachment.name or 'document'
        ext = os.path.splitext(name)[1].lower()
        values = {
            'name': escape(name),
            'mode': 'docx' if ext in OOXML_EXTENSIONS or attachment.mimetype in (
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
                'application/vnd.ms-word.document.macroenabled.12') else 'pdf',
            'content_url': escape('/web/content/%s?%s' % (
                attachment.id, urlencode(token))),
            'pdf_url': escape('/word_preview/%s?%s' % (
                attachment.id, urlencode(token))),
            'download_url': escape('/web/content/%s?%s' % (
                attachment.id, urlencode(dict(token, download='true')))),
            'edit_button': (
                '<a href="/word_editor/open/%s" target="_top" '
                'class="wv-edit">Modifier dans Odoo</a>' % attachment.id
                if request.env.user._is_internal() else ''),
        }
        return request.make_response(
            VIEWER_HTML.format(**values),
            headers=[('Content-Type', 'text/html; charset=utf-8'),
                     ('X-Content-Type-Options', 'nosniff')])


class WordEditorController(http.Controller):

    @http.route('/word_editor/open/<int:attachment_id>', type='http',
                auth='user', methods=['GET'])
    def word_editor_open(self, attachment_id, **kwargs):
        """ « Modifier dans Odoo » : ouvre le fichier Word dans l'éditeur. """
        try:
            attachment = request.env['ir.binary']._find_record(
                res_model='ir.attachment', res_id=attachment_id)
        except (MissingError, AccessError):
            raise request.not_found()
        if not attachment._word_preview_is_word():
            raise request.not_found()
        try:
            record = request.env['word.document']._open_for_attachment(
                attachment)
        except UserError as error:
            return request.make_response(
                '<html><body style="font-family:sans-serif;padding:2em">'
                '<h3>Ouverture impossible</h3><p>%s</p></body></html>'
                % escape(error.args[0]),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
                status=422)
        return request.redirect(
            '/odoo/action-word_preview.action_word_document/%s' % record.id)

    @http.route('/word_editor/<int:document_id>/download', type='http',
                auth='user', methods=['GET'])
    def word_editor_download(self, document_id, **kwargs):
        record = request.env['word.document'].browse(document_id).exists()
        if not record:
            raise request.not_found()
        try:
            record.check_access('read')
        except AccessError:
            raise request.not_found()
        data, extension, mimetype = record._export_bytes()
        return request.make_response(data, headers=[
            ('Content-Type', mimetype),
            ('Content-Length', str(len(data))),
            ('Content-Disposition', content_disposition(
                record._export_filename(extension))),
        ])
