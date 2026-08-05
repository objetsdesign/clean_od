# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Description des outils au format "function calling" générique.
# Convertie ensuite au format attendu par OpenAI ou Anthropic dans ai_chat_session.py
AI_TOOL_SCHEMAS = [
    {
        "name": "search_invoices",
        "description": (
            "Recherche des factures clients ou fournisseurs (et avoirs) dans Odoo. "
            "Utilise ceci pour toute question sur les factures, montants dus, factures impayées, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "move_type": {
                    "type": "string",
                    "enum": ["out_invoice", "out_refund", "in_invoice", "in_refund"],
                    "description": "out_invoice=facture client, out_refund=avoir client, "
                                   "in_invoice=facture fournisseur, in_refund=avoir fournisseur. "
                                   "Si non précisé, cherche out_invoice.",
                },
                "partner_name": {"type": "string", "description": "Nom (partiel) du client ou fournisseur."},
                "payment_state": {
                    "type": "string",
                    "enum": ["not_paid", "in_payment", "paid", "partial", "reversed"],
                    "description": "Filtrer par état de paiement.",
                },
                "state": {
                    "type": "string",
                    "enum": ["draft", "posted", "cancel"],
                    "description": "Filtrer par état du document (posted = validée).",
                },
                "date_from": {"type": "string", "description": "Date de début au format YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Date de fin au format YYYY-MM-DD."},
            },
        },
    },
    {
        "name": "search_quotations",
        "description": (
            "Recherche des devis / commandes de vente dans Odoo (sale.order). "
            "Utilise ceci pour toute question sur les devis envoyés, commandes en cours, chiffre d'affaires vente, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "partner_name": {"type": "string", "description": "Nom (partiel) du client."},
                "state": {
                    "type": "string",
                    "enum": ["draft", "sent", "sale", "done", "cancel"],
                    "description": "draft=brouillon, sent=devis envoyé, sale=commande confirmée.",
                },
                "date_from": {"type": "string", "description": "Date de début YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Date de fin YYYY-MM-DD."},
            },
        },
    },
    {
        "name": "search_purchase_orders",
        "description": (
            "Recherche des commandes / devis d'achat fournisseur dans Odoo (purchase.order). "
            "Utilise ceci pour toute question sur les achats, commandes fournisseurs en cours, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "partner_name": {"type": "string", "description": "Nom (partiel) du fournisseur."},
                "state": {
                    "type": "string",
                    "enum": ["draft", "sent", "purchase", "done", "cancel"],
                    "description": "draft=brouillon, sent=envoyée, purchase=commande confirmée.",
                },
                "date_from": {"type": "string", "description": "Date de début YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Date de fin YYYY-MM-DD."},
            },
        },
    },
    {
        "name": "get_stock_quantity",
        "description": (
            "Donne la quantité en stock disponible/prévue d'un ou plusieurs produits. "
            "Utilise ceci pour toute question du type 'combien reste-t-il de X en stock'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "Nom (partiel) ou référence du produit."},
                "location_name": {"type": "string", "description": "Nom partiel de l'emplacement de stock (optionnel)."},
                "only_low_stock": {
                    "type": "boolean",
                    "description": "Si vrai, ne renvoie que les produits dont le stock est à 0 ou négatif.",
                },
            },
        },
    },
    {
        "name": "search_stock_moves",
        "description": (
            "Recherche des bons de livraison / réceptions / transferts de stock (stock.picking). "
            "Utilise ceci pour les questions sur les livraisons en attente, réceptions, mouvements de stock."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "partner_name": {"type": "string", "description": "Nom (partiel) du partenaire."},
                "picking_type": {
                    "type": "string",
                    "enum": ["incoming", "outgoing", "internal"],
                    "description": "Type de mouvement.",
                },
                "state": {
                    "type": "string",
                    "enum": ["draft", "waiting", "confirmed", "assigned", "done", "cancel"],
                    "description": "État du transfert.",
                },
            },
        },
    },
]


class AiChatTools(models.AbstractModel):
    """Mixin regroupant les fonctions exécutées côté serveur quand l'IA
    demande un 'tool call'. Chaque méthode respecte les droits d'accès
    de self.env.user (pas de sudo), pour ne jamais exposer de données
    interdites à l'utilisateur qui discute avec l'assistant.
    """
    _name = 'ai.chat.tools'
    _description = "Outils de recherche Odoo pour l'assistant IA"

    def _get_limit(self):
        return int(self.env['ir.config_parameter'].sudo().get_param(
            'ai_chat_assistant.max_results', 20)) or 20

    @api.model
    def execute_tool(self, name, arguments):
        """Dispatch générique: exécute l'outil `name` avec les `arguments`
        (dict) fournis par le modèle IA, et renvoie un résultat sérialisable
        en JSON (jamais un objet recordset)."""
        handlers = {
            "search_invoices": self._tool_search_invoices,
            "search_quotations": self._tool_search_quotations,
            "search_purchase_orders": self._tool_search_purchase_orders,
            "get_stock_quantity": self._tool_get_stock_quantity,
            "search_stock_moves": self._tool_search_stock_moves,
        }
        handler = handlers.get(name)
        if not handler:
            return {"error": "Outil inconnu: %s" % name}
        try:
            return handler(arguments or {})
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Erreur lors de l'exécution de l'outil IA %s", name)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Implémentations
    # ------------------------------------------------------------------
    def _tool_search_invoices(self, args):
        Move = self.env['account.move']
        domain = [("move_type", "=", args.get("move_type") or "out_invoice")]
        if args.get("partner_name"):
            domain.append(("partner_id.name", "ilike", args["partner_name"]))
        if args.get("payment_state"):
            domain.append(("payment_state", "=", args["payment_state"]))
        if args.get("state"):
            domain.append(("state", "=", args["state"]))
        if args.get("date_from"):
            domain.append(("invoice_date", ">=", args["date_from"]))
        if args.get("date_to"):
            domain.append(("invoice_date", "<=", args["date_to"]))

        moves = Move.search(domain, limit=self._get_limit(), order="invoice_date desc")
        return {
            "count_found": len(moves),
            "results": [
                {
                    "reference": m.name,
                    "partner": m.partner_id.display_name,
                    "date": str(m.invoice_date or ""),
                    "due_date": str(m.invoice_date_due or ""),
                    "total": m.amount_total,
                    "residual_due": m.amount_residual,
                    "currency": m.currency_id.name,
                    "payment_state": m.payment_state,
                    "state": m.state,
                }
                for m in moves
            ],
        }

    def _tool_search_quotations(self, args):
        Order = self.env['sale.order']
        domain = []
        if args.get("partner_name"):
            domain.append(("partner_id.name", "ilike", args["partner_name"]))
        if args.get("state"):
            domain.append(("state", "=", args["state"]))
        if args.get("date_from"):
            domain.append(("date_order", ">=", args["date_from"]))
        if args.get("date_to"):
            domain.append(("date_order", "<=", args["date_to"]))

        orders = Order.search(domain, limit=self._get_limit(), order="date_order desc")
        return {
            "count_found": len(orders),
            "results": [
                {
                    "reference": o.name,
                    "partner": o.partner_id.display_name,
                    "date": str(o.date_order or ""),
                    "total": o.amount_total,
                    "currency": o.currency_id.name,
                    "state": o.state,
                }
                for o in orders
            ],
        }

    def _tool_search_purchase_orders(self, args):
        Order = self.env['purchase.order']
        domain = []
        if args.get("partner_name"):
            domain.append(("partner_id.name", "ilike", args["partner_name"]))
        if args.get("state"):
            domain.append(("state", "=", args["state"]))
        if args.get("date_from"):
            domain.append(("date_order", ">=", args["date_from"]))
        if args.get("date_to"):
            domain.append(("date_order", "<=", args["date_to"]))

        orders = Order.search(domain, limit=self._get_limit(), order="date_order desc")
        return {
            "count_found": len(orders),
            "results": [
                {
                    "reference": o.name,
                    "partner": o.partner_id.display_name,
                    "date": str(o.date_order or ""),
                    "total": o.amount_total,
                    "currency": o.currency_id.name,
                    "state": o.state,
                }
                for o in orders
            ],
        }

    def _tool_get_stock_quantity(self, args):
        Quant = self.env['stock.quant']
        domain = [("location_id.usage", "=", "internal")]
        if args.get("product_name"):
            domain.append("|")
            domain.append(("product_id.name", "ilike", args["product_name"]))
            domain.append(("product_id.default_code", "ilike", args["product_name"]))
        if args.get("location_name"):
            domain.append(("location_id.display_name", "ilike", args["location_name"]))

        quants = Quant.search(domain, limit=self._get_limit() * 3)
        # Agrégation par produit (un produit peut avoir plusieurs emplacements/lots)
        by_product = {}
        for q in quants:
            key = q.product_id.id
            entry = by_product.setdefault(key, {
                "product": q.product_id.display_name,
                "reference": q.product_id.default_code or "",
                "quantity_on_hand": 0.0,
                "quantity_forecast": 0.0,
                "uom": q.product_uom_id.name,
            })
            entry["quantity_on_hand"] += q.quantity
            entry["quantity_forecast"] += q.quantity - q.reserved_quantity

        results = list(by_product.values())
        if args.get("only_low_stock"):
            results = [r for r in results if r["quantity_on_hand"] <= 0]

        return {"count_found": len(results), "results": results[: self._get_limit()]}

    def _tool_search_stock_moves(self, args):
        Picking = self.env['stock.picking']
        domain = []
        if args.get("partner_name"):
            domain.append(("partner_id.name", "ilike", args["partner_name"]))
        if args.get("picking_type"):
            domain.append(("picking_type_id.code", "=", args["picking_type"]))
        if args.get("state"):
            domain.append(("state", "=", args["state"]))

        pickings = Picking.search(domain, limit=self._get_limit(), order="scheduled_date desc")
        return {
            "count_found": len(pickings),
            "results": [
                {
                    "reference": p.name,
                    "partner": p.partner_id.display_name if p.partner_id else "",
                    "type": p.picking_type_id.name,
                    "scheduled_date": str(p.scheduled_date or ""),
                    "state": p.state,
                    "origin": p.origin or "",
                }
                for p in pickings
            ],
        }
