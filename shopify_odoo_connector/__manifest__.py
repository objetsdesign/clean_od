# -*- coding: utf-8 -*-
{
    "name": "Shopify Odoo Connector",
    "version": "18.0.4.0.0",
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

Nouveautés v4.0 :
------------------
* Catalogue et clients PARTAGEABLES entre plusieurs boutiques Shopify : un
  même produit (ou une même variante, ou un même client) peut désormais
  être lié à PLUSIEURS boutiques à la fois (auparavant : une seule boutique
  par produit/client). Un onglet "Shopify" est ajouté sur la fiche produit
  et sur la fiche contact : y ajouter une ligne (juste la boutique, sans ID
  Shopify) exporte automatiquement le produit/client vers cette boutique
  supplémentaire.
* Deux nouvelles cases par boutique (fiche boutique) : "Catalogue partagé"
  et "Clients partagés". Activées, l'anti-doublon peut réutiliser un
  produit/client déjà lié à une AUTRE boutique (même SKU/code-barres/nom ou
  même email) au lieu d'en créer un doublon : utile pour un scénario
  multi-marques avec catalogue ou base clients commune. Désactivées (valeur
  par défaut), le comportement antérieur est conservé à l'identique.
* Le stock est désormais poussé vers TOUTES les boutiques dont un
  emplacement (Shopify Location) est mappé sur l'entrepôt concerné, avec
  l'identifiant d'inventaire Shopify propre à chaque lien.

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

Nouveautés v3.2 :
------------------
* Nouveau tableau de bord statistique (Shopify > Dashboard) : chiffre
  d'affaires et commandes dans le temps, panier moyen, clients acheteurs,
  répartition du CA par boutique, top produits, dernières commandes.
  Filtres par boutique et par période, comparaison automatique à la
  période précédente.

Nouveautés v3.1 :
------------------
* Réglages Shopify (Configuration > Réglages) avec deux cases anti-doublon :
  ne pas dupliquer un produit déjà existant (match SKU/code-barres/nom,
  produits à variante unique) et ne pas dupliquer un client déjà existant
  (match email).
* Fréquence de la synchronisation automatique (cron) configurable
  directement depuis les Réglages.
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
        "web_editor",
    ],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "data/shopify_webhook_topics_data.xml",
        "data/shopify_display_migration.xml",
        "data/shopify_marketplace_data.xml",
        "views/shopify_config_views.xml",
        "views/shopify_webhook_log_views.xml",
        "views/shopify_sync_log_views.xml",
        "views/shopify_mapping_views.xml",
        "views/shopify_marketplace_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/stock_warehouse_views.xml",
        "views/stock_picking_views.xml",
        "views/shopify_sales_views.xml",
        "views/shopify_config_extra_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "shopify_odoo_connector/static/src/scss/shopify_dashboard.scss",
            "shopify_odoo_connector/static/src/js/dashboard/shopify_dashboard.js",
            "shopify_odoo_connector/static/src/js/dashboard/shopify_dashboard.xml",
        ],
    },
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
