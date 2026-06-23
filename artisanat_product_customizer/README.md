# Artisanat Product Customizer (Odoo 18)

Configurateur de personnalisation produit façon **Zakeke**, intégré à la fiche
produit de votre boutique **Odoo eCommerce** : texte, image, cliparts, polices,
couleurs, aperçu en temps réel et impact prix dynamique.

---

## 1. Installation

1. Copiez le dossier `artisanat_product_customizer/` dans votre répertoire
   d'addons (ex : `/mnt/extra-addons/`).
2. Redémarrez le service Odoo.
3. Activez le **mode développeur**, puis *Apps → Mettre à jour la liste des
   applications*.
4. Recherchez **Artisanat Product Customizer** et installez-le.

Dépendances : `website_sale`, `sale_management` (incluses dans Odoo Community/
Enterprise avec le site web eCommerce).

> Fabric.js (moteur du canvas) est chargé automatiquement depuis un CDN.
> Pour l'auto-héberger, voir `static/lib/fabric/README.md`.

---

## 2. Configurer un produit personnalisable

1. Allez dans **Site Web / Ventes → Produits**, ouvrez un produit.
2. Onglet **Personnalisation** :
   - cochez **Produit personnalisable** ;
   - renseignez les frais (forfait, prix par texte, prix par image) ;
   - sélectionnez les **polices**, **couleurs** et **cliparts** proposés ;
   - ajoutez une ou plusieurs **zones personnalisables** en définissant leur
     cadre en pourcentage de l'image (gauche / haut / largeur / hauteur).
3. Enregistrez et publiez le produit.

Les listes de polices, couleurs et cliparts se gèrent depuis le menu
**Personnalisation → Configuration**.

---

## 3. Côté client

Sur la fiche produit, un bloc **« Personnaliser ce produit »** apparaît :
le client compose son design, voit le supplément se mettre à jour, puis
**Ajouter au panier (personnalisé)**. Le design (aperçu + fichier d'impression
HD + définition JSON) est enregistré et rattaché à la ligne de commande.

---

## 4. Côté gestion

- **Personnalisation → Personnalisations clients** : tous les designs reçus.
- Sur chaque **commande**, une colonne *Aperçu* montre la vignette ;
  ouvrez la personnalisation pour récupérer le **fichier d'impression HD**.

---

## 5. Structure du module

```
artisanat_product_customizer/
├── __manifest__.py
├── controllers/main.py          # routes config / save / add-to-cart
├── models/
│   ├── customization_area.py    # zones, polices, couleurs, cliparts
│   ├── product_template.py       # activation + sérialisation config
│   ├── product_customization.py  # design client (JSON + rendus)
│   └── sale_order_line.py        # rattachement + prix
├── security/ir.model.access.csv
├── data/customization_data.xml   # séquence, polices/couleurs par défaut
├── views/                        # back-office + templates site web
└── static/                       # JS (Fabric.js), CSS, descriptions
```

## Licence
LGPL-3
