import re
from odoo import models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _is_vonros(self):
        """True si la société s'appelle Von Ros / Von Ross / VONROS ... (insensible à la casse)."""
        self.ensure_one()
        return bool(re.search(r'von\s*ros', self.name or '', re.IGNORECASE))
