{
    'name': 'Report Order Invoice',
    'version': '1.0',
    'summary': 'Report Order invoice Objets Design',
    'description': '''
        Améliore l’affichage et l’édition des produits sur le site web Odoo.
        Permet l’édition des produits en front-end, l’affichage enrichi des prix,
        et l'intégration avec les modèles de commandes pour une meilleure expérience client.
    ''',
    'author': "Objets Design",
    'license': 'LGPL-3',
    'website': "https://www.objetsdesign.com/",
    'images': ['module_icon.png',
               ],

    'category': 'Website',
    'depends': ['base', 'sale', 'website','website_sale', 'website_sale_comparison', 'web','stock','purchase', 'account'],


    'data': [
    'security/ir.model.access.csv',
    'data/ir_sequence_data.xml',
    'data/menu_item.xml',
    'data/invoice_template_mail.xml',
    'data/devis_commande_template_mail.xml',
    'data/achat_commande_mail.xml',
    'views/product_product.xml',
    'views/sale_order.xml',
    'views/purchase_order.xml',
    'views/account_move.xml',
    'views/res_partner.xml',
    'views/res_company.xml',
    'views/stock_piking.xml',  # attention: tu avais “stock_piking”, vérifie l’orthographe
    'report/purchase_report.xml',
    'report/devis_template_od.xml',
    'report/facture_template_od.xml',
    'report/delivery_template.xml',
],
    'post_init_hook': 'assign_partner_sequence_to_existing',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
