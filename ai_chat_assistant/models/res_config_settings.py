# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_chat_provider = fields.Selection(
        selection=[
            ('openai', 'OpenAI (ou compatible: Mistral, Groq, Ollama...)'),
            ('anthropic', 'Anthropic (Claude)'),
        ],
        string="Fournisseur IA",
        config_parameter='ai_chat_assistant.provider',
        default='openai',
    )
    ai_chat_api_key = fields.Char(
        string="Clé API",
        config_parameter='ai_chat_assistant.api_key',
    )
    ai_chat_model = fields.Char(
        string="Modèle",
        config_parameter='ai_chat_assistant.model',
        help="Ex: gpt-4o-mini pour OpenAI, claude-sonnet-4-6 pour Anthropic.",
    )
    ai_chat_base_url = fields.Char(
        string="URL de l'API (optionnel)",
        config_parameter='ai_chat_assistant.base_url',
        help="Laisser vide pour utiliser l'URL officielle du fournisseur. "
             "Utile pour un endpoint compatible OpenAI auto-hébergé (Ollama, LM Studio, etc.).",
    )
    ai_chat_max_results = fields.Integer(
        string="Nombre max de lignes renvoyées par recherche",
        config_parameter='ai_chat_assistant.max_results',
        default=20,
    )
