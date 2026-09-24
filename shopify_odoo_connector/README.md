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

## v4.1 — Séparer la fiche Amazon de la fiche Etsy (OrderBridge)

**Problème :** l'app Amazon et OrderBridge lisent toutes les deux les champs
*standards* du produit Shopify (titre, description, photos, tags, prix).
Elles ignorent les métachamps `marketplace_*`. Avec un seul produit Shopify,
Etsy recevait donc forcément la fiche Amazon.

**Solution :** un mode de publication par marketplace
(Shopify > Configuration > Marketplaces).

| Marketplace | Mode | Résultat dans Shopify |
|---|---|---|
| Amazon | Fiche principale | Produit principal = contenu Amazon (lu par l'app Amazon) |
| Etsy | Produit dédié | 2ᵉ produit Shopify, type « Etsy », SKU `-ETSY`, non publié sur la boutique en ligne, contenu Etsy |
| Autres | Métachamps | Métachamps sur le produit principal |

Configuration Shopify / OrderBridge (une seule fois) :

1. Shopify > Produits > Collections > Créer une collection **automatique** :
   condition « Type de produit est égal à Etsy ».
2. OrderBridge > Product Push : filtrer sur cette collection, pousser
   Title, Description, Images, Tags, Price, **SKU**, Quantity.
3. App Amazon : exclure le type de produit « Etsy » (ou cette collection).

Le produit dédié n'est jamais réimporté dans Odoo ; son stock suit le stock
Odoo réel ; les commandes Etsy arrivées dessus sont rattachées au bon article.
Après un changement de mode, utiliser le bouton « Renvoyer les produits vers
Shopify » sur la fiche marketplace.

## v4.2 — Amazon ≠ Etsy avec UN SEUL produit Shopify (recommandé)

```
                 ┌─> Produit Shopify UNIQUE (contenu Amazon) ─> app Amazon ─> Amazon
1 produit Odoo ──┤                                          └─> OrderBridge : commandes, suivi, stock, photos
                 └─> API Etsy : titre / description / tags / prix de la ligne Etsy ─> annonce Etsy
```

Mise en place (une fois) :

1. Etsy : https://www.etsy.com/developers/your-apps > créer une app, copier
   **Keystring** et **Shared secret**, et déclarer comme *Callback URL*
   l'« URL de rappel » affichée sur la fiche marketplace Etsy dans Odoo
   (`https://<votre-odoo>/shopify/etsy/oauth/callback`, en https).
2. Odoo : Shopify > Configuration > Marketplaces > Etsy : mode
   « Annonce Etsy mise à jour directement (API Etsy) », coller Keystring +
   Shared secret, cliquer **Connecter Etsy**, autoriser, puis **Tester la
   connexion**. Régler le taux de conversion si la boutique Etsy n'est pas
   dans la devise d'Odoo.
3. OrderBridge > Product Push : pour les pushs, **décocher Title,
   Description, Tags et Price** (sinon OrderBridge remet le contenu Amazon) ;
   garder Images, Quantity, SKU. Le premier push (Create New Draft) crée
   l'annonce et écrit le métachamp `orderbridge/etsy_listing_id` : Odoo
   retrouve alors l'annonce tout seul.
4. Produit : ligne Etsy de l'onglet Shopify > onglet Etsy > « Envoyer vers
   Etsy maintenant » (ensuite automatique à chaque enregistrement).

Les quantités Etsy ne sont jamais modifiées par Odoo (OrderBridge).

## v4.3 — 1 produit Odoo (2 fiches) -> 1 produit Shopify (2 fiches)

```
1 produit Odoo            1 produit Shopify
 ├─ fiche Etsy   ──────>  champs standards (titre, description, prix, image, tags) ──> OrderBridge ──> Etsy
 └─ fiche Amazon ──────>  métachamps marketplace_amazon.* (title, description, price,
                          media_urls, bullet_points, brand, gtin, search_terms, ...) ──> app Amazon
```

* Shopify > Configuration > Marketplaces : Etsy = « Champs standards du produit
  Shopify », Amazon = « Métachamps uniquement » (réglé automatiquement).
* La fiche Odoo (nom, prix, description, photos) n'est jamais modifiée, ni
  à l'envoi, ni au retour des webhooks Shopify.
* OrderBridge : pousser normalement (Title, Description, Price, Tags,
  Images, Quantity, SKU) : c'est la fiche Etsy.
* App Amazon : mapper titre / description / prix sur les métachamps
  `marketplace_amazon.title`, `.description`, `.price`.

## v4.4 — Seuls les produits à fiche Etsy dans OrderBridge

Odoo gère une collection Shopify **« Etsy (OrderBridge) »** (non publiée sur la
boutique en ligne) : un produit y est ajouté dès qu'il a une fiche Etsy dans
Odoo, et retiré dès que cette fiche est supprimée.

* OrderBridge > Product Push : filtrer par la collection « Etsy (OrderBridge) ».
* Première fois : Shopify > Configuration > Marketplaces > Etsy > « Renvoyer les
  produits vers Shopify » pour remplir la collection.
* Le nom de la collection se change sur la fiche boutique Shopify dans Odoo.

## v4.5 — Les 2 fiches visibles en ouvrant le produit dans Shopify

Odoo crée une fois pour toutes des définitions de métachamps **épinglées**
(« Amazon – Titre », « Amazon – Description », « Amazon – Prix », « Amazon –
Points clés », ...). En ouvrant le produit dans Shopify :

* en haut (Titre, Description, Prix, Photos) : **fiche Etsy** — lue par OrderBridge ;
* carte **Métachamps** en bas : **fiche Amazon**.

Bouton manuel : fiche boutique Shopify dans Odoo > « Afficher la fiche Amazon
dans Shopify ». Scope OAuth/app requis : `write_products`.

## v4.6 — Liste cliquable « Fiches marketplace » sur le produit Shopify

Sur la page du produit dans Shopify, carte Métachamps :

```
Fiches marketplace :  [ Fiche Amazon ]  [ Fiche Etsy ]
```

Un clic sur **Fiche Amazon** ouvre la fiche Amazon ; un clic sur **Fiche Etsy**
ouvre la fiche Etsy (titre, description, prix, photos, tags, détails, et
« Envoyée à »). Les fiches sont créées / mises à jour / supprimées par Odoo à
chaque envoi. Les champs standards du produit restent la fiche Etsy (OrderBridge).

**Scopes à ajouter** à l'app Shopify (token direct : Shopify admin > Apps >
Développer des apps > votre app > Configuration Admin API) :
`read_metaobjects, write_metaobjects, read_metaobject_definitions,
write_metaobject_definitions`, puis réinstaller l'app et recopier le token.

## v4.7 — Liste « Fiche active » : Fiche Amazon / Fiche Etsy

Produit Shopify > carte Métachamps > **Fiche active** (ou onglet Shopify du
produit dans Odoo) :

* **Fiche Etsy** → le produit Shopify prend le titre / description / prix /
  photo / tags Etsy → **OrderBridge** l'envoie vers Etsy (Product Push).
* **Fiche Amazon** → le produit Shopify prend la fiche Amazon → l'**app Amazon**
  l'envoie vers Amazon.

Le changement fait dans Shopify arrive dans Odoo par webhook (products/update),
Odoo met à jour le produit Shopify quelques secondes après. La fiche Odoo n'est
jamais modifiée.

Attention : l'app Amazon ou OrderBridge envoient ce qui est affiché AU MOMENT
de leur synchronisation. Désactivez la synchro automatique du titre/description
dans l'app Amazon si vous basculez souvent sur « Fiche Etsy ».
