# -*- coding: utf-8 -*-
{
    'name': 'Delete Done Manufacturing Order',
    'version': '1.0',
    'summary': 'Allow deletion of done manufacturing orders (DANGEROUS)',
    'description': """
Ajoute un bouton "Force Delete" sur les ordres de fabrication (mrp.production)
à l'état "Terminé" (done), permettant de tout dévalider et de supprimer
l'ordre de fabrication ainsi que ses mouvements de stock, lignes de
mouvement, ordres de travail et écritures de valorisation associées.

ATTENTION : cette suppression est irréversible et casse la traçabilité
comptable/stock. A utiliser uniquement en connaissance de cause, puis à
désinstaller après usage.
""",
    'author': 'Custom',
    'category': 'Manufacturing',
    'depends': ['mrp'],
    'data': [
        'views/mrp_production_view.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'application': False,
}
