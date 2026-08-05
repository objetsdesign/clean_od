# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from .ai_chat_tools import AI_TOOL_SCHEMAS

_logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un assistant intégré à un ERP Odoo. Tu aides l'utilisateur à
retrouver rapidement des informations sur les FACTURES, les DEVIS/commandes de vente,
les COMMANDES D'ACHAT et le STOCK (quantités disponibles, livraisons, réceptions).

Règles impératives:
- Tu n'inventes JAMAIS de chiffres ou de références. Pour toute question portant sur des
  données de l'entreprise, tu DOIS appeler l'outil correspondant et baser ta réponse
  uniquement sur son résultat.
- Si un outil ne renvoie aucun résultat, dis-le clairement, ne suppose rien.
- Réponds de façon concise, en français, avec les chiffres et références utiles
  (numéro de facture/devis/commande, montants, dates, quantités).
- Si la demande est ambiguë (ex: plusieurs clients possibles), demande une précision
  plutôt que de deviner.
"""

MAX_TOOL_ROUNDS = 5


class AiChatSession(models.Model):
    _name = 'ai.chat.session'
    _description = "Session de chat avec l'assistant IA"
    _order = 'write_date desc'

    name = fields.Char(default="Nouvelle conversation")
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    message_ids = fields.One2many('ai.chat.message', 'session_id')
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # API appelée depuis le widget JS (via this.orm.call)
    # ------------------------------------------------------------------
    def send_message(self, body):
        """Ajoute le message utilisateur, interroge l'IA (avec appels d'outils
        si nécessaire), enregistre et renvoie la réponse de l'assistant."""
        self.ensure_one()
        body = (body or "").strip()
        if not body:
            return {}

        self.env['ai.chat.message'].create({
            'session_id': self.id, 'role': 'user', 'body': body,
        })
        if self.name == "Nouvelle conversation":
            self.name = body[:60]

        provider = self.env['ir.config_parameter'].sudo().get_param('ai_chat_assistant.provider', 'openai')
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_chat_assistant.api_key')
        model = self.env['ir.config_parameter'].sudo().get_param('ai_chat_assistant.model')
        base_url = self.env['ir.config_parameter'].sudo().get_param('ai_chat_assistant.base_url')

        if not api_key:
            answer = ("⚠️ Aucune clé API configurée. Va dans Réglages > Technique > "
                       "Assistant IA pour renseigner le fournisseur, la clé API et le modèle.")
            msg = self.env['ai.chat.message'].create({
                'session_id': self.id, 'role': 'assistant', 'body': answer,
            })
            return {'id': msg.id, 'role': 'assistant', 'body': answer}

        history = [{'role': m.role, 'content': m.body}
                   for m in self.message_ids if m.role in ('user', 'assistant')]

        try:
            if provider == 'anthropic':
                answer = self._run_anthropic(history, api_key, model, base_url)
            else:
                answer = self._run_openai(history, api_key, model, base_url)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Erreur assistant IA")
            answer = "⚠️ Erreur lors de l'appel au fournisseur IA: %s" % exc

        msg = self.env['ai.chat.message'].create({
            'session_id': self.id, 'role': 'assistant', 'body': answer,
        })
        return {'id': msg.id, 'role': 'assistant', 'body': answer}

    # ------------------------------------------------------------------
    # OpenAI (et tout endpoint compatible "chat completions")
    # ------------------------------------------------------------------
    def _run_openai(self, history, api_key, model, base_url):
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        model = model or "gpt-4o-mini"
        tools = [{"type": "function", "function": t} for t in AI_TOOL_SCHEMAS]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

        for _round in range(MAX_TOOL_ROUNDS):
            resp = requests.post(
                url,
                headers={"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "tools": tools, "tool_choice": "auto"},
                timeout=60,
            )
            if resp.status_code >= 400:
                raise UserError("OpenAI API (%s): %s" % (resp.status_code, resp.text[:500]))
            data = resp.json()
            choice = data["choices"][0]["message"]
            tool_calls = choice.get("tool_calls")

            if not tool_calls:
                return choice.get("content") or "(réponse vide)"

            messages.append(choice)
            for call in tool_calls:
                fn = call["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self.env['ai.chat.tools'].execute_tool(fn["name"], args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, default=str),
                })

        return "Je n'ai pas réussi à obtenir une réponse définitive (trop d'étapes)."

    # ------------------------------------------------------------------
    # Anthropic (Claude)
    # ------------------------------------------------------------------
    def _run_anthropic(self, history, api_key, model, base_url):
        url = (base_url or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
        model = model or "claude-sonnet-4-6"
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                 for t in AI_TOOL_SCHEMAS]

        messages = [{"role": h["role"], "content": h["content"]} for h in history]

        for _round in range(MAX_TOOL_ROUNDS):
            resp = requests.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1500,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": tools,
                },
                timeout=60,
            )
            if resp.status_code >= 400:
                raise UserError("Anthropic API (%s): %s" % (resp.status_code, resp.text[:500]))
            data = resp.json()
            content_blocks = data.get("content", [])
            messages.append({"role": "assistant", "content": content_blocks})

            tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
            if not tool_use_blocks:
                text_blocks = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
                return "\n".join(text_blocks).strip() or "(réponse vide)"

            tool_results = []
            for block in tool_use_blocks:
                result = self.env['ai.chat.tools'].execute_tool(block["name"], block.get("input") or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(result, default=str),
                })
            messages.append({"role": "user", "content": tool_results})

        return "Je n'ai pas réussi à obtenir une réponse définitive (trop d'étapes)."
