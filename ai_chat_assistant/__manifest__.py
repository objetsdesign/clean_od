# -*- coding: utf-8 -*-
{
    'name': "AI Chat Assistant",
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': "Assistant IA conversationnel: factures, devis, achats, stock",
    'description': """
Assistant IA pour Odoo (simple chat)
=====================================
Ajoute un menu "Assistant IA" avec une fenêtre de chat très simple permettant
de poser des questions en langage naturel sur:
  - les factures / avoirs (account.move)
  - les devis / commandes de vente (sale.order)
  - les commandes d'achat (purchase.order)
  - le stock disponible (stock.quant) et les mouvements (stock.picking)

Le module ne remplace pas la recherche Odoo native: il fait appel à un
fournisseur d'IA externe (OpenAI, Anthropic ou tout endpoint compatible
"OpenAI Chat Completions") configurable dans Réglages > Technique > Assistant IA.
L'IA ne "devine" jamais les chiffres: elle appelle des fonctions internes
qui interrogent la base Odoo réelle (avec les droits d'accès de
l'utilisateur connecté) puis reformule la réponse.
""",
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account', 'sale', 'purchase', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_chat_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_chat_assistant/static/src/js/ai_chat_action.js',
            'ai_chat_assistant/static/src/xml/ai_chat_templates.xml',
            'ai_chat_assistant/static/src/scss/ai_chat.scss',
        ],
    },
    'installable': True,
    'application': True,
}
