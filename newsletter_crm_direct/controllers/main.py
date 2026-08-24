# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class WebsiteMassMailingCRM(http.Controller):

    @http.route(
        ['/website_mass_mailing/subscribe/crm'],
        type='json',
        website=True,
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def subscribe(self, value=None, source=None, **post):

        email = post.get('email') or value
        _logger.info("📩 Subscribe CRM: email=%s source=%s", email, source)

        if not email:
            return {'success': False, 'message': _('Email requis')}

        CrmLead = request.env['crm.lead'].sudo()
        CrmStage = request.env['crm.stage'].sudo()
        CrmTeam = request.env['crm.team'].sudo()
        MailingList = request.env['mailing.list'].sudo()
        MailingContact = request.env['mailing.contact'].sudo()
        UtmSource = request.env['utm.source'].sudo()
        Partner = request.env['res.partner'].sudo()

        # -------------------------------------------------
        # 1️⃣ TEAM
        # -------------------------------------------------
        team = CrmTeam.search([('name', '=', 'Marketing Leads')], limit=1)
        if not team:
            team = CrmTeam.create({'name': 'Marketing Leads'})

        # -------------------------------------------------
        # 2️⃣ STAGE
        # -------------------------------------------------
        stage = CrmStage.search([
            ('name', '=', 'Marketing Leads'),
            ('team_id', '=', team.id)
        ], limit=1)

        if not stage:
            stage = CrmStage.create({
                'name': 'Marketing Leads',
                'sequence': 1,
                'team_id': team.id,
            })

        # -------------------------------------------------
        # 🌐 SOURCE CRM = NEWSLETTER
        # -------------------------------------------------
        source_name = 'Newsletter'

        source_rec = UtmSource.search([
            ('name', '=', source_name)
        ], limit=1)

        if not source_rec:
            source_rec = UtmSource.create({
                'name': source_name
            })

        # 👉 correction : on ne crée PAS un partner "Newsletter"
        # on va utiliser le vrai partner avec email

        # -------------------------------------------------
        # 👤 PARTNER (CORRECTION PROPRE)
        # -------------------------------------------------
        partner = Partner.search([('email', '=', email)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': email,
                'email': email,
            })
        if source_rec:
            partner.write({
                'source_id': source_rec.id
            })
        # -------------------------------------------------
        # 📬 MAILING LIST SAFE FIX
        # -------------------------------------------------
        mailing_list = MailingList.search([
            ('name', '=', 'Newsletter Website')
        ], limit=1)

        if not mailing_list:
            mailing_list = MailingList.create({
                'name': 'Newsletter Website'
            })

        # -------------------------------------------------
        # 👤 CONTACT
        # -------------------------------------------------
        contact = MailingContact.search([('email', '=', email)], limit=1)
        if not contact:
            contact = MailingContact.create({'email': email})

        # subscription (éviter doublon)
        existing_sub = request.env['mailing.subscription'].sudo().search([
            ('contact_id', '=', contact.id),
            ('list_id', '=', mailing_list.id),
        ], limit=1)

        if not existing_sub:
            request.env['mailing.subscription'].sudo().create({
                'contact_id': contact.id,
                'list_id': mailing_list.id,
            })

        # -------------------------------------------------
        # 🎯 CRM LEAD
        # -------------------------------------------------
        existing = CrmLead.search([('email_from', '=', email)], limit=1)

        if not existing:
            CrmLead.create({
                'name': f'Newsletter - {email}',
                'email_from': email,
                'type': 'opportunity',
                'team_id': team.id,
                'stage_id': stage.id,
                'source_id': source_rec.id,
            })

        _logger.info("✅ OK newsletter + CRM with source")

        return {
            'success': True,
            'message': _('Inscription réussie avec succès.')
        }