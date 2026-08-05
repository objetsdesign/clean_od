# AI Chat Assistant — module Odoo 18

Assistant IA conversationnel simple pour Odoo : un chat qui répond aux questions
sur les **factures**, **devis/commandes de vente**, **commandes d'achat** et le
**stock**, en interrogeant directement votre base Odoo (pas d'invention de chiffres).

## Installation

1. Copier le dossier `ai_chat_assistant` dans votre dossier `addons` (ou custom-addons).
2. Redémarrer Odoo, puis dans **Apps** : "Mettre à jour la liste des applications",
   chercher "AI Chat Assistant", cliquer sur **Installer**.
3. Aller dans **Réglages > Technique** (mode développeur) ou directement dans le
   panneau **Réglages Généraux** (une section "Assistant IA" apparaît en bas si
   vous êtes administrateur) :
   - Choisir le **fournisseur** : OpenAI (ou tout endpoint compatible : Mistral,
     Groq, Ollama...) ou Anthropic (Claude).
   - Renseigner la **clé API**.
   - Renseigner le **modèle** (ex: `gpt-4o-mini`, `claude-sonnet-4-6`).
   - (Optionnel) une **URL d'API** personnalisée si vous utilisez un endpoint
     auto-hébergé compatible OpenAI.
4. Ouvrir le menu **Assistant IA > Discuter avec l'assistant**.

## Fonctionnement

- Chaque question de l'utilisateur est envoyée au modèle IA choisi.
- Si la question nécessite des données réelles (montant d'une facture, stock
  d'un produit, etc.), le modèle appelle une **fonction interne** (function
  calling / tool use) qui exécute une vraie recherche Odoo (`search_read`)
  **avec les droits d'accès de l'utilisateur connecté** (pas de `sudo()`).
- Le résultat de la recherche est renvoyé au modèle, qui formule la réponse
  finale en français.

Outils disponibles pour l'instant :
- `search_invoices` — factures et avoirs clients/fournisseurs (account.move)
- `search_quotations` — devis et commandes de vente (sale.order)
- `search_purchase_orders` — commandes d'achat (purchase.order)
- `get_stock_quantity` — quantités en stock par produit (stock.quant)
- `search_stock_moves` — livraisons / réceptions / transferts (stock.picking)

## Exemples de questions

- « Combien de factures impayées pour le client Azur SARL ? »
- « Quel est le stock disponible du produit REF-1234 ? »
- « Liste les devis envoyés ce mois-ci non encore confirmés. »
- « Quelles commandes fournisseur sont encore en brouillon ? »
- « Y a-t-il des livraisons en attente pour le client Dupont ? »

## Étendre le module

Pour ajouter un nouvel outil (ex: interroger la comptabilité analytique, les
projets, les RH...) :
1. Ajouter sa description JSON-schema dans `AI_TOOL_SCHEMAS`
   (`models/ai_chat_tools.py`).
2. Ajouter la méthode `_tool_xxx(self, args)` correspondante.
3. L'enregistrer dans le dispatcher `execute_tool`.

Le reste (appel OpenAI/Anthropic, boucle de tool-calling, interface de chat)
fonctionne automatiquement avec le nouvel outil.

## Sécurité / bonnes pratiques

- Les recherches respectent les droits d'accès Odoo standards de
  l'utilisateur connecté (règles d'enregistrement, multi-société, etc.).
- La clé API est stockée comme paramètre système (`ir.config_parameter`),
  visible uniquement des administrateurs (`base.group_system`).
- Aucune donnée n'est envoyée au fournisseur IA en dehors des résultats
  strictement nécessaires à la réponse (pas de dump de la base).
