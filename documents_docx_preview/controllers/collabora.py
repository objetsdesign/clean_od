"""Ouverture dans Collabora Online quand le connecteur officiel est installé.

Si le module `collabora_odoo` (Collabora Productivity) est installé et que
l'adresse du serveur Collabora est renseignée, le clic sur un Word ou un
PowerPoint ouvre Collabora ; sinon, les éditeurs LibreOffice de ce module
restent utilisés. Désactivable avec le paramètre système
`docx_preview.use_collabora` = `False`.
"""
from odoo.exceptions import AccessError, MissingError
from odoo.http import request


def collabora_url(document):
    """Adresse de l'éditeur Collabora pour ce document, ou None."""
    params = request.env["ir.config_parameter"].sudo()
    if (params.get_param("docx_preview.use_collabora", "True") or "").lower() in ("0", "false", "no", "non"):
        return None
    if not params.get_param("cool_public_url"):
        return None
    installed = request.env["ir.module.module"].sudo().search_count(
        [("name", "=", "collabora_odoo"), ("state", "=", "installed")])
    if not installed or not document.attachment_id:
        return None
    try:
        document.check_access("write")
        mode = "write"
    except (AccessError, MissingError):
        mode = "view"
    return "/collabora_odoo/frame/%s/%s" % (document.attachment_id.id, mode)
