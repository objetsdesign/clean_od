# Shopify Odoo Connector (Odoo 18)

Connecteur bidirectionnel complet et **temps réel** entre Shopify et Odoo 18,
basé sur une **application publique OAuth** (multi-boutiques) et les
**webhooks Shopify**.

## Fonctionnalités

| Domaine        | Shopify -> Odoo (webhook)                     | Odoo -> Shopify (temps réel)              |
|----------------|------------------------------------------------|--------------------------------------------|
| Produits       | `products/create`, `products/update`, `products/delete` | écriture sur `product.template` / `product.product` |
| Stock          | `inventory_levels/update`                       | écriture sur `stock.quant` (qty dispo)     |
| Clients        | `customers/create`, `customers/update`, `customers/delete` | écriture sur `res.partner`           |
| Commandes      | `orders/create`, `orders/updated`, `orders/paid`, `orders/cancelled` | `action_cancel()` sur `sale.order` |
| Paiements      | transactions de la commande (`orders/paid`)     | création automatique `account.payment`     |
| Livraisons     | `fulfillments/create`, `fulfillments/update`    | `button_validate()` sur `stock.picking` -> création fulfillment + tracking |
| Désinstallation| `app/uninstalled`                               | -                                            |

Une **tâche planifiée de réconciliation** (désactivée par défaut) sert de
filet de sécurité en complément des webhooks.

## Installation

1. Copier le dossier `shopify_odoo_connector` dans votre dossier `addons` Odoo 18.
2. Installer le paquet Python `requests` s'il n'est pas déjà présent :
   `pip install requests`
3. Mettre à jour la liste des applications puis installer **"Shopify Odoo Connector"**.

## Deux modes d'authentification

Le champ **"Mode d'authentification"** sur la fiche boutique propose :

### 1. Token direct (recommandé, une seule boutique)

1. Dans l'admin Shopify, allez sur **Apps > Développer des applications**
   (ou via le **Dev Dashboard** : `admin.shopify.com` > Settings > Apps >
   Develop apps > Build apps using Dev Dashboard).
2. Créez une app, configurez les **scopes** (accès produits, commandes,
   clients, inventaire, fulfillments), puis installez-la sur votre boutique.
3. Récupérez le **token d'accès Admin API** (Admin API access token) dans
   l'onglet **API credentials**.
4. Dans Odoo, menu **Shopify > Boutiques > Créer** : nom, domaine boutique,
   mode = "Token direct", collez le token dans **Token d'accès Admin API**.
5. (Optionnel mais recommandé) Copiez aussi le **Client Secret** visible dans
   le même onglet API credentials, dans le champ dédié : il sert uniquement
   à vérifier la signature HMAC des webhooks reçus.
6. Cliquez sur **Connecter** : aucune redirection, aucun redirect_uri à
   configurer. Les webhooks sont enregistrés automatiquement.

Ce mode évite complètement les erreurs `redirect_uri is not whitelisted`
puisqu'il n'y a pas de flux OAuth.

### 2. OAuth (application publique, multi-boutiques)

À réserver aux cas où l'app doit être installée par plusieurs boutiques
différentes (ex. distribution sur l'App Store Shopify).

1. Sur https://partners.shopify.com (ou le Dev Dashboard), créez une app avec
   une **distribution publique**.
2. Dans l'onglet Versions > Create version, renseignez l'**App URL** et
   ajoutez l'URL de callback dans **Redirect URLs** :
   `https://VOTRE-DOMAINE-ODOO/shopify/oauth/callback`
3. Récupérez le **Client ID** et le **Client Secret**.
4. Dans Odoo, mode = "OAuth", renseignez Client ID/Secret, puis cliquez sur
   **Connecter (OAuth)**.

## Après la connexion (les deux modes)

Utilisez les boutons **Importer produits / clients / commandes** pour un
premier import complet, puis laissez les webhooks prendre le relais pour la
synchronisation temps réel.

## Points d'attention avant mise en production

- **File d'attente asynchrone** : les appels sortants (`_shopify_push_one`,
  etc.) sont actuellement synchrones. Pour un fort volume, il est recommandé
  de les faire passer par `queue_job` (OCA) afin de ne pas bloquer les
  requêtes utilisateur.
- **Boucles de synchronisation** : le contexte `shopify_sync=True` est utilisé
  pour éviter les boucles infinies Shopify -> Odoo -> Shopify. Vérifiez son
  usage si vous étendez le module.
- **Gestion des devises / taxes** : à adapter selon votre configuration
  fiscale (le mapping actuel est simplifié).
- **Réconciliation comptable** : les paiements créés (`account.payment`) ne
  sont pas automatiquement lettrés aux factures ; à connecter selon votre
  flux de facturation.
- Testez d'abord sur une boutique **de développement** Shopify.
