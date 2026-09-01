from . import models


def post_init_hook(env):
    """Après l'installation/mise à niveau du module, crée automatiquement le produit
    Odoo (product.template) pour toute référence catalogue qui n'en a pas encore
    (ex. références de démo ou existantes créées avant l'automatisation), et,
    inversement, crée une référence catalogue pour tout produit Odoo existant qui
    n'en a pas encore (pour que le dashboard catalogue couvre tous les produits Odoo)."""
    products_without_tmpl = env['catalog.product'].search([('product_tmpl_id', '=', False)])
    if products_without_tmpl:
        products_without_tmpl._auto_create_product_template()
    env['catalog.product']._sync_all_odoo_products()
