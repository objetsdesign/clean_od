# -*- coding: utf-8 -*-
""" Éditeur Word dans Odoo : comme « Ouvrir avec Odoo Feuille de calcul »
pour Excel, un fichier Word est ouvert dans l'éditeur de texte d'Odoo, puis
réenregistré dans le fichier Word d'origine (ou téléchargé en .docx). """
import base64
import hashlib
import logging
import os
import re

from lxml import etree, html as lxml_html
from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# format d'origine -> (filtre LibreOffice d'export, extension, mimetype)
EXPORT_FILTERS = {
    '.docx': ('docx:MS Word 2007 XML', '.docx',
              'application/vnd.openxmlformats-officedocument.'
              'wordprocessingml.document'),
    '.doc': ('doc:MS Word 97', '.doc', 'application/msword'),
    '.odt': ('odt:writer8', '.odt', 'application/vnd.oasis.opendocument.text'),
    '.rtf': ('rtf:Rich Text Format', '.rtf', 'application/rtf'),
}
DATA_URI_RE = re.compile(r'^data:(image/[\w.+-]+);base64,(.*)$', re.S)
WEB_IMAGE_RE = re.compile(r'^/web/(?:image|content)/(\d+)')


class WordDocument(models.Model):
    _name = 'word.document'
    _description = "Document Word (éditeur Odoo)"
    _inherit = ['mail.thread']
    _order = 'write_date desc, id desc'

    name = fields.Char(string="Nom", required=True, tracking=True)
    body = fields.Html(string="Contenu", sanitize_style=False,
                       strip_style=False)
    attachment_id = fields.Many2one(
        'ir.attachment', string="Fichier Word d'origine", readonly=True,
        ondelete='set null', index=True)
    source_checksum = fields.Char(readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string="Société",
                                 default=lambda self: self.env.company)
    last_saved_date = fields.Datetime(
        string="Dernier enregistrement dans le fichier", readonly=True,
        copy=False)

    # ------------------------------------------------------------------
    # Import : Word -> HTML (éditeur Odoo)
    # ------------------------------------------------------------------
    def _cache_model(self):
        return self.env['word.preview.cache']

    @api.model
    def _word_to_html(self, data, filename):
        ext = os.path.splitext(filename or '')[1].lower() or '.docx'
        raw = self._cache_model()._run_soffice(
            data, ext, 'html:HTML (StarWriter):EmbedImages', '.html',
            filename=filename)
        text = raw.decode('utf-8', errors='replace')
        document = lxml_html.document_fromstring(text)
        body = document.find('body')
        if body is None:
            return text
        parts = [body.text or ''] + [
            etree.tostring(child, encoding='unicode', method='html')
            for child in body]
        return ''.join(parts)

    def _store_inline_images(self, html_content):
        """ Remplace les images en base64 par des pièces jointes (contenu
        plus léger, compatible avec l'éditeur). """
        self.ensure_one()
        if not html_content or 'data:image' not in html_content:
            return html_content
        root = lxml_html.fragment_fromstring(html_content, create_parent='div')
        Attachment = self.env['ir.attachment'].sudo()
        for index, img in enumerate(root.iter('img')):
            match = DATA_URI_RE.match(img.get('src') or '')
            if not match:
                continue
            mimetype, data = match.groups()
            extension = mimetype.split('/')[-1].split('+')[0]
            attachment = Attachment.create({
                'name': 'image_%s.%s' % (index + 1, extension),
                'datas': data,
                'mimetype': mimetype,
                'res_model': self._name,
                'res_id': self.id,
            })
            attachment.generate_access_token()
            img.set('src', '/web/image/%s?access_token=%s' % (
                attachment.id, attachment.access_token))
        return ''.join(
            [root.text or ''] + [etree.tostring(c, encoding='unicode',
                                                method='html') for c in root])

    def _load_from_attachment(self, attachment):
        """ (Re)charge le contenu depuis le fichier Word. """
        self.ensure_one()
        data = attachment.raw or b''
        html_content = self._word_to_html(data, attachment.name)
        self.write({
            'body': self._store_inline_images(html_content),
            'source_checksum': attachment.checksum or hashlib.sha1(
                data).hexdigest(),
        })

    @api.model
    def _open_for_attachment(self, attachment):
        """ Retourne la copie modifiable de l'utilisateur courant pour ce
        fichier (créée au besoin). `attachment` doit déjà être contrôlé. """
        record = self.search([('attachment_id', '=', attachment.id),
                              ('create_uid', '=', self.env.uid)], limit=1)
        if record and record.source_checksum == attachment.checksum:
            return record
        if not record:
            record = self.create({
                'name': attachment.name,
                'attachment_id': attachment.id,
            })
            record._load_from_attachment(attachment.sudo())
        else:
            # Le fichier a été remplacé ailleurs depuis : on recharge.
            record._load_from_attachment(attachment.sudo())
            record._message_log(body=_(
                "Le fichier Word d'origine a changé : contenu rechargé."))
        return record

    def action_reload_from_source(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Ce document n'est lié à aucun fichier Word."))
        self.attachment_id.check_access('read')
        self._load_from_attachment(self.attachment_id.sudo())
        self._message_log(body=_("Contenu rechargé depuis le fichier Word."))
        return True

    # ------------------------------------------------------------------
    # Export : HTML -> Word
    # ------------------------------------------------------------------
    def _html_for_export(self):
        """ HTML complet, images réintégrées en base64 (LibreOffice ne peut
        pas lire les URL protégées d'Odoo). """
        self.ensure_one()
        content = self.body or '<p></p>'
        root = lxml_html.fragment_fromstring(content, create_parent='div')
        Attachment = self.env['ir.attachment'].sudo()
        for img in root.iter('img'):
            match = WEB_IMAGE_RE.match(img.get('src') or '')
            if not match:
                continue
            attachment = Attachment.browse(int(match.group(1))).exists()
            if not attachment or not (
                    (attachment.res_model == self._name
                     and attachment.res_id == self.id)
                    or attachment.public):
                continue
            img.set('src', 'data:%s;base64,%s' % (
                attachment.mimetype or 'image/png',
                base64.b64encode(attachment.raw or b'').decode()))
        inner = ''.join(
            [root.text or ''] + [etree.tostring(c, encoding='unicode',
                                                method='html') for c in root])
        return ('<!DOCTYPE html><html><head><meta charset="utf-8"/>'
                '<title>%s</title></head><body>%s</body></html>' % (
                    escape(self.name or ''), inner))

    def _target_format(self):
        self.ensure_one()
        ext = os.path.splitext(
            (self.attachment_id.name or self.name or ''))[1].lower()
        return EXPORT_FILTERS.get(ext, EXPORT_FILTERS['.docx'])

    def _export_bytes(self, export_format=None):
        self.ensure_one()
        convert_to, extension, mimetype = export_format or self._target_format()
        data = self._cache_model()._run_soffice(
            self._html_for_export().encode('utf-8'), '.html', convert_to,
            extension, infilter='HTML (StarWriter)',
            filename=self.name)
        return data, extension, mimetype

    def _export_filename(self, extension):
        base = os.path.splitext(self.name or 'document')[0] or 'document'
        return base + extension

    def action_save_to_source(self):
        """ Réécrit le fichier Word d'origine avec le contenu modifié. """
        self.ensure_one()
        attachment = self.attachment_id
        if not attachment:
            raise UserError(_(
                "Ce document n'est lié à aucun fichier Word : utilisez "
                "« Télécharger .docx »."))
        # Droits d'écriture sur le fichier d'origine (et son document).
        attachment.check_access('write')
        data, extension, mimetype = self._export_bytes()
        attachment.write({'raw': data, 'mimetype': mimetype})
        self.write({
            'source_checksum': attachment.checksum,
            'last_saved_date': fields.Datetime.now(),
        })
        self._message_log(body=_("Enregistré dans le fichier « %s ».",
                                 attachment.name))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Fichier Word enregistré"),
                'message': _("« %s » a été mis à jour.", attachment.name),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_download_docx(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/word_editor/%s/download' % self.id,
            'target': 'self',
        }

    def action_preview_source(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Ce document n'est lié à aucun fichier Word."))
        return self.attachment_id.action_word_preview()
