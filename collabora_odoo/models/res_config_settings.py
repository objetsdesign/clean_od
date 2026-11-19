# -*- coding: utf-8 -*-
# Copyright the Collabora Online contributors.
#
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cool_public_url = fields.Char(
        "Collabora Online Server URL")
    cool_disable_cert_check = fields.Boolean(
        "Disable certificate checks (for development only)",
        default=False)
    cool_wopi_host_url = fields.Char(
        "Odoo URL")
    cool_jwt_secret = fields.Char(
        "JWT Secret")
    cool_jwt_ttl = fields.Integer(
        "Token TTL",
        default=86400)

    def set_values(self):
        super().set_values()
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('cool_public_url', self.cool_public_url)
        set_param('cool_disable_cert_check', self.cool_disable_cert_check)
        set_param('cool_wopi_host_url', self.cool_wopi_host_url)
        set_param('cool_jwt_secret', self.cool_jwt_secret)
        set_param('cool_jwt_ttl', self.cool_jwt_ttl)

    @api.model
    def get_values(self):
        res = super().get_values()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        res['cool_public_url'] = get_param('cool_public_url')
        res['cool_disable_cert_check'] = get_param('cool_disable_cert_check')
        res['cool_wopi_host_url'] = get_param('cool_wopi_host_url')
        res['cool_jwt_secret'] = get_param('cool_jwt_secret')
        res['cool_jwt_ttl'] = get_param('cool_jwt_ttl')
        return res
