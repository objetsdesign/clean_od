# Suivi Devis & Commandes — B2B / Fund Raising / Asie

Module Odoo 18 reprenant le fichier Excel **"Suivi_Devis_Commandes_OD - B2B FUND ASIE"** :
mêmes colonnes, mêmes statuts, mêmes indicateurs — dans une application Odoo avec un
tableau de bord visuel, des relances, et un lien automatique Devis → Commande.

## Installation

1. Copier le dossier `b2b_fund_asie_tracking` dans votre dossier d'addons Odoo 18
   (`addons-path`).
2. Activer le **mode développeur** (Réglages → Général → Activer le mode développeur).
3. Aller dans **Apps**, cliquer sur **Mettre à jour la liste des applications**.
4. Rechercher "Suivi Devis & Commandes" et cliquer sur **Installer**.
5. (Optionnel) Pour tester avec des données d'exemple issues du fichier Excel d'origine,
   installez Odoo avec le paramètre `--load-language` habituel + activez les données de
   démonstration à la création de la base (case "Données de démonstration").

## Structure du module

| Excel | Odoo |
|---|---|
| Onglet **DEVIS B2B / FUND / ASIE** | Menu *Suivi Devis & Commandes → [Activité] → Devis* (modèle `b2fa.quote`, champ `activity_type`) |
| Onglet **COMMANDES B2B / FUND / ASIE** | Menu *Suivi Devis & Commandes → [Activité] → Commandes* (modèle `b2fa.order`, champ `activity_type`) |
| Onglet **TABLEAU DE BORD** | Menu *Suivi Devis & Commandes → Tableau de Bord* (widget OWL, temps réel) |
| Onglet **GUIDE UTILISATION** | Menu *Suivi Devis & Commandes → Guide d'utilisation* |

## Fonctionnement

* Un **devis** peut être transféré en **commande** en un clic (bouton "Transférer en
  commande"), qui pré-remplit toutes les informations.
* Le **solde à recevoir** (`amount_ht - deposit_received`) et la **marge**
  (`amount_ht - cost`) sont calculés automatiquement.
* Les commandes en retard de livraison sont automatiquement signalées (ruban rouge +
  filtre dédié).
* Numérotation automatique : `DEV-B2B-2026-001`, `CMD-FUND-2026-001`, etc.
* Le tableau de bord recalcule tous les KPIs en direct depuis la base (pas de cache),
  identiques à ceux du fichier Excel (total devis, taux de conversion, CA, acomptes,
  solde à encaisser, etc.), pour chaque activité et en vue consolidée globale.

## Alimenter le tableau de bord

Ce module a son propre modèle de données (`b2fa.quote` / `b2fa.order`), séparé du
module standard **Ventes** (`sale.order`). Le tableau de bord affiche donc "0" tant
qu'aucun devis/commande n'a été saisi ou importé ici — même si des devis/commandes
existent déjà dans Ventes. Trois façons de l'alimenter :

1. **Saisie manuelle** dans les menus Devis / Commandes de chaque activité.
2. **Import depuis Excel** (menu *Importer depuis Excel*) : relit le fichier
   "Suivi Devis & Commandes" d'origine (mêmes onglets par activité) et crée les
   devis/commandes correspondants. Les imports successifs du même fichier ne créent
   pas de doublons.
3. **Synchronisation depuis Ventes** (automatique) : reprend les devis/commandes
   du module Ventes standard, **sans action manuelle après la classification**.
   - Ouvrez *Classer les Devis/Commandes (Ventes)*, filtrez/regroupez (par équipe
     commerciale, source, client...) pour repérer des lots homogènes, sélectionnez
     les lignes concernées et renseignez la colonne "Activité" (**B2B Classique
     / Fund Raising / Asie**) — vous pouvez éditer plusieurs lignes sélectionnées
     en une seule fois. Depuis une commande, le bouton "Classer en Asie" fait
     la même chose en un clic.
   - Dès l'enregistrement, la ligne est **immédiatement** créée/actualisée dans le
     Suivi Devis & Commandes (devis, et commande si le devis Ventes est déjà
     confirmé) — pas besoin de cliquer sur "Synchroniser" ni d'attendre.
   - Toute modification ultérieure d'un devis/commande déjà classé (client,
     montant, statut, lignes...) déclenche aussi une resynchronisation immédiate.
   - **Important côté données** : "Asie" est un choix normal du champ Activité,
     mais il est routé en interne vers des modèles 100% séparés
     (`b2fa.quote.asie` / `b2fa.order.asie`), sans aucune relation Odoo avec
     `b2fa.quote` / `b2fa.order` (B2B/Fund Raising). Choisir "Asie" crée/retrouve
     automatiquement une fiche technique `sale.order.sky` qui porte ce lien —
     visible dans *Suivi Devis & Commandes → Asie → Devis/Commandes Ventes
     classés*, pas besoin d'y toucher au quotidien.
   - Le menu *Synchroniser depuis Ventes* et la tâche planifiée horaire restent
     disponibles comme filet de sécurité (utile après un import en masse qui
     contournerait l'enregistrement normal, par exemple) — ils couvrent les
     trois activités.
   - Champs propres à ce module (production, transport, acompte, statut détaillé de
     commande...) ne viennent pas de Ventes : ils restent à compléter ici et ne sont
     jamais écrasés par la synchronisation une fois la commande créée.

## Sécurité

Deux groupes sont fournis dans la catégorie "Suivi Devis & Commandes" :

* **Utilisateur** : lecture / écriture / création sur devis et commandes.
* **Responsable** : accès complet (y compris suppression).

## Note de migration (18.0.1.0.0 → 18.0.1.1.0)

Si votre base contenait déjà des devis/commandes "Asie" créés avant que
l'activité Asie devienne un modèle séparé (`b2fa.quote.asie` /
`b2fa.order.asie`), une migration automatique s'exécute à la mise à jour du
module : elle recopie ces enregistrements vers les nouveaux modèles, rétablit
le lien vers Ventes (`sale.order.sky` + champ Activité) puis supprime les
anciens enregistrements devenus obsolètes dans `b2fa.quote` / `b2fa.order`.
Rien à faire manuellement — mettez simplement le module à jour (Apps → ⋮ →
Mettre à jour).
