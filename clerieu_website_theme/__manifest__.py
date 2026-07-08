{
    'name': 'Clerieu Website Theme Customization',
    'version': '1.0',
    'summary': "Personnalisations du site web Clerieu (header, footer, homepage, boutique, blog)",
    'description': """
Module qui centralise toutes les personnalisations visuelles du site web
(header, footer, page d'accueil, page boutique, page blog) via des vues
héritées, afin de ne plus modifier directement les vues natives d'Odoo.

Organisation du code :
- models/  : logique métier Python (vide pour le moment, prêt à l'emploi)
- views/   : templates QWeb (XML) purs, sans CSS/JS en ligne
- static/src/css/ : feuilles de style, une par zone du site
- static/src/js/  : scripts, un par zone du site
""",
    'category': 'Website',
    'author': 'Clerieu',
    'depends': [
        'website',
        'website_sale',
        'website_blog',
    ],
    'data': [
        'views/website_shared_design.xml',
        'views/website_header.xml',
        'views/website_footer.xml',
        'views/website_homepage.xml',
        'views/website_shop_products.xml',
        'views/website_product_page.xml',
        'views/website_blog_posts.xml',
        'views/website_story_page.xml',
    ],
    'assets': {
        'website.assets_frontend': [
            # CSS - ordre : design partagé d'abord, puis zones spécifiques
            # 'clerieu_website_theme/static/src/css/shared_design.css',
            'clerieu_website_theme/static/src/css/header.css',
            'clerieu_website_theme/static/src/css/homepage.css',
            # 'clerieu_website_theme/static/src/css/shop_products.css',
            # 'clerieu_website_theme/static/src/css/product_page.css',
            # 'clerieu_website_theme/static/src/css/blog_posts.css',
            # JS
            'clerieu_website_theme/static/src/js/header.js',
            'clerieu_website_theme/static/src/js/shop_products.js',
            'clerieu_website_theme/static/src/js/product_page.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
