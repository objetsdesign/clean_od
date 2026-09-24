# -*- coding: utf-8 -*-
{
    "name": "Shopify Odoo Connector",
    "version": "18.0.5.0.0",
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

Nouveautés v5.0 : changement de fiche complet, rapide, sans chevauchement
-------------------------------------------------------------------------
* Changer "Fiche active" remplace TOUT le contenu du produit Shopify :
  titre, description, prix et SKU de chaque variante, photo principale +
  galerie de la fiche, tags, type de produit, aperçu moteurs de
  recherche (le stock reste le stock réel Odoo, commun aux 2 fiches).
* Le webhook répond immédiatement à Shopify ; le renvoi se fait en
  arrière-plan juste après (tâche déclenchée à la demande). Fini les
  doubles envois quand Shopify renvoyait le webhook (> 5 s).
* Seuls les métachamps modifiés sont renvoyés (changement plus rapide).
* Auto-correction : si une ancienne page Shopify est enregistrée avec
  l'ancien contenu, Odoo remet automatiquement la fiche active.

Nouveautés v4.9 : "Fiche active" = liste déroulante envoyée par Odoo
--------------------------------------------------------------------
* Le produit Shopify affiche une liste déroulante "Fiche active" dont
  les choix (Fiche Amazon, Fiche Etsy, ...) sont envoyés par Odoo et
  mis à jour automatiquement. Choisir + Enregistrer -> Odoo remplace le
  contenu du produit Shopify par la fiche choisie.
* Ne dépend plus des métaobjets (fonctionne avec le seul scope
  write_products) ; toujours pré-rempli avec la fiche actuelle.
* Remplace le sélecteur de métaobjet de la v4.8 (vide tant qu'aucune
  fiche n'existait).

Nouveautés v4.8 : sélecteur (many2one) "Fiche active" dans Shopify
-------------------------------------------------------------------
* "Fiche active" devient un sélecteur qui ne propose QUE les fiches
  existant dans Odoo pour ce produit ("Fiche Amazon — <produit>",
  "Fiche Etsy — <produit>"). Une fiche d'un autre produit est refusée.
* Page produit Shopify épurée : seul "Fiche active" reste épinglé ; les
  métachamps Amazon détaillés et la liste de toutes les fiches sont
  désépinglés (visibles via "Tout afficher"), l'ancien champ texte est
  supprimé.

Nouveautés v4.7 : liste "Fiche active" (Fiche Amazon / Fiche Etsy)
-------------------------------------------------------------------
* Liste déroulante "Fiche active" sur le produit Shopify ET dans Odoo.
  Fiche Etsy -> titre / description / prix / photo / tags du produit
  Shopify = fiche Etsy (envoyée par OrderBridge vers Etsy). Fiche Amazon
  -> ces champs = fiche Amazon (envoyée par l'app Amazon vers Amazon).
* Changement dans Shopify -> webhook -> Odoo applique et renvoie le
  produit en quelques secondes (sans boucle, fiche Odoo intacte).

Nouveautés v4.6 : liste cliquable "Fiches marketplace" dans Shopify
--------------------------------------------------------------------
* Sur la page produit Shopify, champ épinglé "Fiches marketplace" :
  Fiche Amazon | Fiche Etsy. Un clic ouvre la fiche choisie (titre,
  description, prix, photos, tags, points clés, détails, destination).
  Techniquement : un métaobjet "Fiche marketplace" par fiche, géré
  depuis Odoo (créé, mis à jour, supprimé automatiquement).
* Nouveaux scopes Shopify requis : read/write_metaobjects,
  read/write_metaobject_definitions.

Nouveautés v4.5 : les 2 fiches visibles sur le produit Shopify
--------------------------------------------------------------
* Définitions de métachamps épinglées créées automatiquement : en ouvrant
  le produit dans Shopify, la fiche Etsy est dans les champs standards et
  la fiche Amazon s'affiche en clair dans la carte "Métachamps"
  (Amazon – Titre, Amazon – Description, Amazon – Prix, ...).

Nouveautés v4.4 : seuls les produits à fiche Etsy dans OrderBridge
-------------------------------------------------------------------
* Collection Shopify "Etsy (OrderBridge)" gérée automatiquement : un
  produit y entre dès qu'il a une fiche Etsy dans Odoo, et en sort dès
  qu'elle est supprimée. Dans OrderBridge, filtrer sur cette collection.

Nouveautés v4.3 : 1 produit Odoo (2 fiches) -> 1 produit Shopify
-----------------------------------------------------------------
* Nouveau mode "Champs standards du produit Shopify" (Etsy par défaut) :
  titre / description / prix / image principale / tags de la fiche Etsy
  deviennent ceux du produit Shopify unique, envoyés à Etsy par
  OrderBridge. La fiche Odoo n'est jamais modifiée.
* Amazon passe en "Métachamps" : sa fiche complète (titre, description,
  prix, photos, points clés, marque, GTIN, mots-clés...) est stockée sur
  le MÊME produit Shopify en métachamps marketplace_amazon.*.
* L'import Shopify -> Odoo ne réécrit plus nom / description / prix /
  photos Odoo avec la fiche Etsy.

Nouveautés v4.2 : Amazon ≠ Etsy avec UN SEUL produit Shopify
-------------------------------------------------------------
* Nouveau mode "Annonce Etsy mise à jour directement (API Etsy)", par
  défaut pour Etsy : le produit Shopify (unique) garde le contenu Amazon ;
  Odoo met à jour l'annonce Etsy (titre, description, tags, matériaux,
  qui/quand, prix) via l'API officielle Etsy, avec le contenu de la ligne
  Etsy. OrderBridge garde commandes, suivi et stock.
* L'annonce Etsy est retrouvée automatiquement grâce au métachamp
  orderbridge/etsy_listing_id écrit par OrderBridge (ou n° saisi).
* Connexion Etsy OAuth 2.0 (PKCE) depuis la fiche marketplace Etsy.
* Migration : Etsy repasse d'office en mode API et les produits Shopify
  dédiés Etsy créés en v4.1 sont supprimés (un seul produit Shopify).

Nouveautés v4.1 : fiche Amazon ≠ fiche Etsy (OrderBridge)
----------------------------------------------------------
* Chaque marketplace a un "Mode de publication Shopify" :
  - Fiche principale (Amazon) : le contenu Amazon devient la fiche
    Shopify principale, lue automatiquement par l'app Amazon.
  - Produit dédié (Etsy) : un produit Shopify SÉPARÉ est créé avec le
    titre / la description / les photos / le prix / les tags Etsy. C'est
    ce produit qu'OrderBridge pousse vers Etsy (Product Push).
  - Métachamps uniquement (autres marketplaces).
* Produit dédié : type de produit "Etsy" (collection automatique),
  SKU suffixé (-ETSY), non publié sur la boutique en ligne, stock = stock
  Odoo réel, jamais réimporté dans Odoo.
* Les commandes Etsy importées par OrderBridge sur le produit dédié sont
  rattachées au bon article Odoo.

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
