# -*- coding: utf-8 -*-
"""v9.47 : une boutique « Connectée » sans jeton d'accès passe en « Erreur »
(visible), pour qu'on la reconnecte."""


def migrate(cr, version):
    cr.execute("""
        UPDATE shopify_config
           SET state = 'error',
               last_error = 'Jeton d''accès manquant : reconnectez la boutique (OAuth ou token direct).'
         WHERE state = 'connected' AND (access_token IS NULL OR access_token = '')
    """)
