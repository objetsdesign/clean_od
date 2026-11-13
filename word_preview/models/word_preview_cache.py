# -*- coding: utf-8 -*-
import base64
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

WORD_EXTENSIONS = ('.docx', '.doc', '.odt', '.rtf', '.docm', '.dotx', '.dot')
WORD_MIMETYPES = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
    'application/vnd.ms-word.document.macroenabled.12',
    'application/msword',
    'application/vnd.oasis.opendocument.text',
    'application/rtf',
    'text/rtf',
)
DEFAULT_TIMEOUT = 120          # secondes
DEFAULT_MAX_SIZE_MB = 30       # au-delà, pas de conversion


class WordPreviewCache(models.Model):
    """ PDF généré à partir d'un fichier Word, indexé par l'empreinte (checksum)
    du fichier source : un même contenu n'est converti qu'une fois, et un
    fichier modifié (nouvelle empreinte) est automatiquement reconverti. """
    _name = 'word.preview.cache'
    _description = "Aperçu Word : cache des PDF"

    checksum = fields.Char(required=True, index=True, readonly=True)
    source_name = fields.Char(readonly=True)
    pdf = fields.Binary(attachment=True, readonly=True)

    _sql_constraints = [
        ('checksum_uniq', 'unique(checksum)',
         "Un aperçu existe déjà pour ce fichier."),
    ]

    # ------------------------------------------------------------------
    # Conversion LibreOffice
    # ------------------------------------------------------------------
    @api.model
    def _get_param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(
            'word_preview.%s' % key, default)

    @api.model
    def _find_soffice(self):
        configured = self._get_param('soffice_path', '')
        candidates = [configured] if configured else []
        candidates += ['soffice', 'libreoffice',
                       '/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice',
                       '/opt/libreoffice/program/soffice',
                       '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                       r'C:\Program Files\LibreOffice\program\soffice.exe']
        for candidate in candidates:
            path = shutil.which(candidate) or (
                os.path.isfile(candidate) and candidate)
            if path:
                return path
        raise UserError(_(
            "LibreOffice est introuvable sur le serveur Odoo : installez-le "
            "(ex. « sudo apt install libreoffice-writer ») ou indiquez son "
            "chemin dans le paramètre système « word_preview.soffice_path »."))

    @api.model
    def _convert_to_pdf(self, data, filename):
        """ Convertit `data` (bytes d'un fichier Word) en PDF (bytes). """
        max_size = int(self._get_param('max_size_mb', DEFAULT_MAX_SIZE_MB))
        if len(data) > max_size * 1024 * 1024:
            raise UserError(_(
                "Fichier trop volumineux pour l'aperçu (%(size)s Mo > "
                "%(max)s Mo). Téléchargez-le pour l'ouvrir.",
                size=round(len(data) / 1024 / 1024, 1), max=max_size))
        soffice = self._find_soffice()
        timeout = int(self._get_param('timeout', DEFAULT_TIMEOUT))
        ext = os.path.splitext(filename or '')[1].lower()
        if ext not in WORD_EXTENSIONS:
            ext = '.docx'
        with tempfile.TemporaryDirectory(prefix='odoo_word_preview_') as tmp:
            source = os.path.join(tmp, 'source' + ext)
            with open(source, 'wb') as f:
                f.write(data)
            # Profil LibreOffice dédié : permet plusieurs conversions en
            # parallèle (workers Odoo) sans conflit de verrou.
            profile = pathlib.Path(tmp, 'profile').as_uri()
            cmd = [soffice, '-env:UserInstallation=%s' % profile,
                   '--headless', '--norestore', '--nologo', '--nodefault',
                   '--nolockcheck', '--convert-to', 'pdf',
                   '--outdir', tmp, source]
            env = dict(os.environ, HOME=tmp)
            try:
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=timeout, env=env, check=False)
            except subprocess.TimeoutExpired:
                raise UserError(_(
                    "La conversion du document a dépassé %s secondes.",
                    timeout))
            output = os.path.join(tmp, 'source.pdf')
            if not os.path.isfile(output):
                _logger.error(
                    "Aperçu Word : échec de conversion de %s (code %s) : %s %s",
                    filename, proc.returncode,
                    proc.stdout.decode(errors='replace'),
                    proc.stderr.decode(errors='replace'))
                raise UserError(_(
                    "Impossible de convertir « %s » en PDF (fichier "
                    "endommagé ou protégé par mot de passe ?).", filename))
            with open(output, 'rb') as f:
                return f.read()

    @api.model
    def _get_pdf(self, checksum, data_getter, filename):
        """ Retourne le PDF du cache, ou le génère. `data_getter` n'est
        appelé qu'en cas de conversion (évite de lire le fichier inutilement).
        """
        cache = self.sudo().search([('checksum', '=', checksum)], limit=1)
        if cache and cache.pdf:
            return base64.b64decode(cache.pdf)
        pdf = self._convert_to_pdf(data_getter(), filename)
        try:
            with self.env.cr.savepoint():
                if cache:
                    cache.write({'pdf': base64.b64encode(pdf)})
                else:
                    self.sudo().create({
                        'checksum': checksum,
                        'source_name': filename,
                        'pdf': base64.b64encode(pdf),
                    })
        except Exception:  # conversion simultanée du même fichier : sans gravité
            _logger.info("Aperçu Word : cache déjà créé pour %s", filename)
        return pdf
