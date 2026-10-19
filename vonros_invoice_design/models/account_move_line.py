import re
from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _vr_ref(self):
        """Colonne Réf. de l'Excel : nom court du modèle (1er mot du nom produit, ex. MOKA, LORA)."""
        self.ensure_one()
        name = (self.product_id.product_tmpl_id.name or '').strip()
        return name.split()[0] if name else ''

    def _vr_designation(self):
        """Colonne Désignation de l'Excel : libellé court sur une ligne + variante.
        Ex. 'MOKA Grand Sac Cabas Femme Moka | Tote Bag XL| ...' (Toffee) -> 'Grand Sac Cabas Femme Moka Toffee'.
        La longue description de vente n'est pas reprise."""
        self.ensure_one()
        product = self.product_id
        if not product:
            first = (self.name or '').strip().split('\n')[0]
            return re.sub(r'^\[[^\]]*\]\s*', '', first)
        name = (product.product_tmpl_id.name or '').strip()
        ref = self._vr_ref()
        if ref and name.startswith(ref):
            name = name[len(ref):].strip()
        name = re.split(r'\s*[|,]\s*', name)[0].strip() or ref
        variant = ', '.join(product.product_template_attribute_value_ids.mapped('name'))
        return f"{name} {variant}".strip()
