# Shopify Odoo Connector (Odoo 18)

Connecteur bidirectionnel complet et **temps réel** entre Shopify et Odoo 18,
basé sur une **application publique OAuth** (multi-boutiques) et les
**webhooks Shopify**.

## Fonctionnalités

| Domaine        | Shopify -> Odoo (webhook)                     | Odoo -> Shopify (temps réel)              |
|----------------|------------------------------------------------|--------------------------------------------|
| Produits       | `products/create`, `products/update`, `products/delete` | écriture sur `product.template` / `product.product` |
| Stock          | `inventory_levels/update`                       | `stock.quant` (création/écriture) **et** validation de tout `stock.move` (réception, livraison, transfert interne, ajustement d'inventaire) |
| Clients        | `customers/create`, `customers/update`, `customers/delete` | écriture sur `res.partner`           |
| Commandes      | `orders/create`, `orders/updated`, `orders/paid`, `orders/cancelled` | `action_cancel()` sur `sale.order` |
| Paiements      | transactions de la commande (`orders/paid`)     | création automatique `account.payment`     |
| Photos        | image principale + galerie + photo par variante (voir ci-dessous) | - |
| Livraisons     | `fulfillments/create`, `fulfillments/update`    | `button_validate()` sur `stock.picking` -> création fulfillment + tracking |
| Désinstallation| `app/uninstalled`                               | -                                            |

Une **tâche planifiée** (`Shopify : synchronisation automatique`, **active
par défaut**, toutes les 15 minutes) importe automatiquement tout ce qui a
changé depuis la dernière synchro (produits, clients, commandes, stock),
en complément des webhooks. Elle est indispensable quand Odoo n'est pas
joignable publiquement en HTTPS (serveur de test, réseau fermé...), car
dans ce cas les webhooks Shopify ne peuvent tout simplement pas atteindre
Odoo. De plus, dès qu'une boutique est connectée (token direct ou OAuth),
un **import complet automatique** (produits, stock, clients, commandes)
se déclenche immédiatement, sans action supplémentaire de l'utilisateur.

## Nouveautés v2.0

- **Import automatique qui fonctionne réellement** : cron actif par défaut
  (15 min, incrémental via `updated_at_min`) + import complet automatique
  juste après la connexion de la boutique. Bouton "Tout importer
  maintenant" en un clic (produits + stock + clients + commandes).
- **Tableau de bord Shopify** (vue Kanban, menu Shopify > Boutiques) :
  compteurs produits / clients / commandes, erreurs des 7 derniers jours,
  raccourcis d'action par boutique.
- **Mapping avancé des taxes** (menu Shopify > Configuration > Mapping des
  taxes) : chaque taxe Shopify (`tax_lines`) est associée à une taxe Odoo
  précise ; un mapping par défaut est créé automatiquement au premier
  import puis reste modifiable.
- **Mapping avancé des livraisons** (menu Shopify > Configuration > Mapping
  des livraisons) : chaque mode de livraison Shopify (`shipping_lines`) est
  associé à un produit Odoo (et, en option, à un transporteur `delivery.carrier`) ;
  la ligne de frais de port est désormais importée automatiquement sur la
  commande de vente, ce qui n'était pas le cas auparavant.

## Installation

1. Copier le dossier `shopify_odoo_connector` dans votre dossier `addons` Odoo 18.
2. Installer le paquet Python `requests` s'il n'est pas déjà présent :
   `pip install requests`
3. Le module dépend de **`website_sale`** (nécessaire pour la galerie de
   photos produit, modèle `product.image`) : il sera installé automatiquement
   avec ses propres dépendances si ce n'est pas déjà le cas.
4. Mettre à jour la liste des applications puis installer **"Shopify Odoo Connector"**.

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

## Synchronisation des mouvements de stock

### Import initial du stock (Shopify -> Odoo)

Après l'import des produits, le module importe automatiquement la
**quantité disponible actuelle sur Shopify** pour chaque emplacement mappé à
un entrepôt, et l'applique dans Odoo via un **ajustement d'inventaire**
standard (ce qui crée les mouvements de stock nécessaires). Sans cet import,
les produits nouvellement créés dans Odoo auraient un stock à 0 et aucun
mouvement entrant/sortant, même si le produit a du stock sur Shopify.

Utilisez le bouton **"Importer stock"** sur la fiche boutique pour relancer
cet import à tout moment (utile si l'écart se creuse, ou en complément des
webhooks `inventory_levels/update` qui gèrent le temps réel au jour le jour).

### Mise à jour temps réel (Odoo -> Shopify)

Toute opération qui modifie le stock d'un produit lié à Shopify déclenche
automatiquement un envoi vers Shopify (`inventory_levels/set`), avec deux
niveaux de déclenchement complémentaires pour plus de fiabilité :

1. **`stock.quant`** (création ou écriture sur la quantité) : couvre la
   plupart des cas (réceptions, livraisons, transferts, ajustements directs).
2. **`stock.move`** (validation, c'est-à-dire passage à l'état "fait") :
   filet de sécurité supplémentaire qui recalcule et repousse le stock pour
   chaque couple (produit, entrepôt) concerné, y compris pour les mouvements
   internes entre deux entrepôts tous deux liés à Shopify.

Dans les deux cas, la quantité réellement envoyée est **le stock physique
moins le stock réservé**, agrégée sur tous les emplacements internes de
l'entrepôt (et non un seul quant/lot isolé), pour refléter fidèlement la
quantité disponible à la vente. Chaque envoi est tracé dans le journal de
synchronisation (Shopify > Journaux > Synchronisations).

## Synchronisation des photos

À chaque import/mise à jour d'un produit (import manuel ou webhook
`products/create`/`products/update`), le module télécharge automatiquement :

- **l'image principale** (première image Shopify, position 1) → champ
  `image_1920` du produit ;
- **les images supplémentaires** (galerie) → onglet "Variantes" du produit,
  section images additionnelles (modèle `product.image`) ;
- **les photos spécifiques à une variante** (ex : une couleur a sa propre
  photo dans Shopify) → champ image de la variante concernée.

Pour éviter de retélécharger inutilement à chaque synchronisation, le module
retient l'ID de chaque image Shopify déjà importée et ne retélécharge que les
images nouvelles ou modifiées côté Shopify.

Cette synchronisation est **actuellement en import seul** (Shopify -> Odoo) ;
les photos ajoutées ou modifiées côté Odoo ne sont pas encore renvoyées vers
Shopify.

## Livraisons (commandes Shopify) et réceptions (fournisseurs)

Par défaut (option **"Confirmer automatiquement les commandes importées"**
activée sur la fiche boutique), chaque commande importée depuis Shopify est
**confirmée automatiquement** dans Odoo, exactement comme si vous cliquiez
sur le bouton "Confirmer" d'un devis. C'est cette confirmation qui déclenche
la création automatique du **bon de livraison** correspondant dans Odoo.

Pour traiter ces livraisons :

1. Allez dans **Inventaire > Opérations > Livraisons** (ou depuis la
   commande de vente elle-même, bouton "Livraison").
2. Une fois la livraison préparée/validée (bouton **"Valider"**), le module
   crée automatiquement le **fulfillment Shopify** correspondant (avec le
   transporteur et le numéro de suivi si renseignés), et pousse la nouvelle
   quantité de stock vers Shopify.

Les **réceptions fournisseurs** (stock entrant, ex : réapprovisionnement)
suivent le fonctionnement standard d'Odoo (**Achats** ou **Inventaire >
Opérations > Réceptions**) : elles ne sont pas liées à Shopify directement,
mais toute réception validée met aussi à jour automatiquement le stock
disponible envoyé à Shopify (voir section précédente).

Si vous préférez garder un contrôle manuel (vérifier chaque commande avant
qu'elle ne génère une livraison), désactivez la case "Confirmer
automatiquement les commandes importées" : les commandes resteront en devis
et vous les confirmerez vous-même depuis **Ventes**.

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
