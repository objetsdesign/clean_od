# -*- coding: utf-8 -*-
import logging
import os

from markupsafe import escape

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import content_disposition, request

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
