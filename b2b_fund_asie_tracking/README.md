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

## Sécurité

Deux groupes sont fournis dans la catégorie "Suivi Devis & Commandes" :

* **Utilisateur** : lecture / écriture / création sur devis et commandes.
* **Responsable** : accès complet (y compris suppression).
