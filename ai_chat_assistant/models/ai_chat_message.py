# -*- coding: utf-8 -*-
from odoo import fields, models


class AiChatMessage(models.Model):
    _name = 'ai.chat.message'
    _description = "Message de l'assistant IA"
    _order = 'create_date asc, id asc'

    session_id = fields.Many2one('ai.chat.session', required=True, ondelete='cascade', index=True)
    role = fields.Selection(
        [('user', 'Utilisateur'), ('assistant', 'Assistant'), ('tool', 'Outil'), ('system', 'Système')],
        required=True, default='user',
    )
    body = fields.Text(string="Contenu")
    tool_name = fields.Char(string="Outil appelé")
