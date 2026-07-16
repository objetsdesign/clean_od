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

## Créer l'application Shopify (Partner Dashboard)

1. Sur https://partners.shopify.com, créez une **application publique**.
2. URL de callback OAuth à renseigner :
   `https://VOTRE-DOMAINE-ODOO/shopify/oauth/callback`
3. Récupérez le **Client ID** et le **Client Secret**.

## Configuration dans Odoo

1. Menu **Shopify > Boutiques > Créer**.
2. Renseignez : nom, domaine (`monshop.myshopify.com`), Client ID, Client Secret.
3. Cliquez sur **Connecter (OAuth)** : vous êtes redirigé vers Shopify pour
   autoriser l'application, puis renvoyé automatiquement vers Odoo.
4. Les webhooks nécessaires sont enregistrés automatiquement à la connexion.
5. Utilisez les boutons **Importer produits / clients / commandes** pour un
   premier import complet, puis laissez les webhooks prendre le relais.

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
