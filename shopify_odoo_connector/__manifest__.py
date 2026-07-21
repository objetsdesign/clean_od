# -*- coding: utf-8 -*-
{
    "name": "Shopify Odoo Connector",
    "version": "18.0.2.0.0",
    "category": "Sales/Sales",
    "summary": "Connecteur bidirectionnel complet entre Shopify et Odoo 18",
    "description": """
Shopify <-> Odoo 18 Connector
==============================
Module complet de synchronisation bidirectionnelle en temps réel (webhooks)
entre une ou plusieurs boutiques Shopify et Odoo 18, via une application
publique OAuth.

Fonctionnalités :
-----------------
* Authentification OAuth (application publique, multi-boutiques)
* Synchronisation Produits & Variantes (Shopify <-> Odoo)
* Synchronisation Stock / Inventaire multi-entrepôts (Shopify Locations)
* Synchronisation Clients
* Synchronisation Commandes (création, mise à jour, annulation)
* Synchronisation Paiements (Shopify Transactions -> Odoo account.payment)
* Synchronisation Livraisons / Expéditions (Fulfillments + tracking)
* Réception des événements Shopify via Webhooks (temps réel)
* Envoi des changements Odoo -> Shopify (temps réel, sur create/write)
* Journal complet des synchronisations et gestion des erreurs / retries
* Sécurité HMAC sur tous les webhooks entrants

Nouveautés v2.0 :
------------------
* Import automatique RÉEL : tâche planifiée active par défaut (15 min,
  incrémentale) + import complet automatique juste après la connexion.
  Ne dépend plus uniquement des webhooks (utile en environnement de test,
  réseau fermé, ou en cas de webhook manqué).
* Tableau de bord Shopify (vue Kanban) : compteurs produits/clients/
  commandes, erreurs récentes, bouton "Tout importer" par boutique.
* Mapping avancé des taxes Shopify -> taxes Odoo (auto-détecté + éditable).
* Mapping avancé des modes de livraison Shopify -> produit/transporteur
  Odoo, avec import automatique de la ligne de frais de port sur la
  commande de vente.
""",
    "author": "Custom Development",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "base_setup",
        "product",
        "stock",
        "sale_management",
        "website_sale",
        "account",
        "delivery",
        "mail",
    ],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "data/shopify_webhook_topics_data.xml",
        "views/shopify_config_views.xml",
        "views/shopify_webhook_log_views.xml",
        "views/shopify_sync_log_views.xml",
        "views/shopify_mapping_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/stock_warehouse_views.xml",
        "views/stock_picking_views.xml",
        "views/menu_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
}
