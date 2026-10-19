# -*- coding: utf-8 -*-
""" Consultation d'un document par une personne externe (sans compte Odoo),
via le lien sécurisé (jeton secret) reçu par email. """
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request


class DocumentExternalShare(http.Controller):

    def _get_external_document(self, document_id, token):
        document = request.env['document.file'].sudo().with_context(
            active_test=False).browse(document_id).exists()
        if not document:
            raise NotFound()
        status = document._get_external_access_status(token)
        if not status:
            raise NotFound()
        return document, status

    @http.route('/document/external/<int:document_id>/<string:token>',
                type='http', auth='public', website=True, sitemap=False)
    def external_document_page(self, document_id, token, **kwargs):
        document, status = self._get_external_document(document_id, token)
        content_url = '/document/external/%s/%s/content' % (document.id, token)
        return request.render(
            'enhanced_document_management.document_external_page', {
                'document': document,
                'status': status,
                'content_url': content_url,
                'is_url': document.content_type == 'url',
            })

    @http.route('/document/external/<int:document_id>/<string:token>/content',
                type='http', auth='public', sitemap=False)
    def external_document_content(self, document_id, token, download=None,
                                  **kwargs):
        document, status = self._get_external_document(document_id, token)
        if status != 'ok':
            raise NotFound()
        if document.content_type == 'url':
            if not document.content_url:
                raise NotFound()
            return request.redirect(document.content_url, local=False)
        attachment = document.attachment_id
        if not attachment:
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(attachment)
        return stream.get_response(as_attachment=bool(download))
