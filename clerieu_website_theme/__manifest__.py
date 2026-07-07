{
    'name': 'Clerieu Website Theme Customization',
    'version': '1.0',
    'summary': "Personnalisations du site web Clerieu (header, footer, homepage, boutique, blog)",
    'description': """
Module qui centralise toutes les personnalisations visuelles du site web
(header, footer, page d'accueil, page boutique, page blog) via des vues
héritées, afin de ne plus modifier directement les vues natives d'Odoo.
""",
    'category': 'Website',
    'author': 'Clerieu',
    'depends': [
        'website',
        'website_sale',
        'website_blog',
    ],
    'data': [
        'views/website_header.xml',
        'views/website_footer.xml',
        'views/website_homepage.xml',
        'views/website_shop_products.xml',
        'views/website_blog_posts.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
