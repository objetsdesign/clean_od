# Catalogue Production — Dashboard (Odoo 18)

Module Odoo 18 pour la gestion et la visualisation du catalogue produit (maroquinerie / textile),
reprenant exactement les champs et la structure du fichier Excel source.

## Contenu

- **Modèles**
  - `catalog.collection` — une collection = un onglet Excel (MOKA, LORA, NOVA, RAYA, ELYA, SORA, SVEN, ERIIK)
  - `catalog.product` — une référence produit, avec tous les champs du fichier Excel :
    SKU, réf. nom, description, dimensions, matières/couleurs (principale, secondaire, doublure),
    motif, accessoires 1 à 6, accessoires cuir, packaging individuel, Prod 1/2, Date livrable 1/2,
    stock, coût de production, photo.
  - Statut de production calculé automatiquement : Réalisé / En cours / 2ème lancement / À planifier.

- **Vues**
  - Tableau de bord Kanban des collections (références, stock, coût moyen, avancement production)
  - Galerie Kanban produit (photo, pastille collection, badge de statut)
  - Liste fidèle à la structure du fichier Excel d'origine
  - Fiche produit détaillée
  - Pivot & Graphique pour l'analyse du stock / coûts / statuts

- **Données**
  - Les 8 collections et les 32 références du fichier Excel source sont importées comme données
    de démonstration (avec photos), directement utilisables après installation.

## Installation

1. Copier le dossier `catalog_dashboard` dans le dossier `addons` de votre instance Odoo 18.
2. Mettre à jour la liste des applications (mode développeur activé).
3. Installer le module « Catalogue Production - Dashboard ».
4. Menu **Catalogue Production** dans la barre d'applications.
