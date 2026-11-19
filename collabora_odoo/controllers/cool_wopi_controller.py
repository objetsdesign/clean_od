# -*- coding: utf-8 -*-
# Copyright the Collabora Online contributors.
#
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import odoo
import json
import time
import urllib
import datetime

from odoo import http
from odoo.http import request
from odoo.addons.collabora_odoo.utils import jwt, discover

class CoolWopiController(odoo.http.Controller):
    # maybe use bearer
    @http.route('/collabora_odoo/wopi/files/<int:attachment_id>', auth='public')
    def file_info(self, attachment_id, access_token, access_token_ttl=0):
        token = jwt.verify_token(request, access_token)
        if 'error' in token:
            return request.make_response(data="Permission denied: {}".format(token['error']), status=401)

        if token['attachment_id'] != attachment_id:
            return request.make_response("Permission denied. Token invalid for file.", status=403)

        attachments = request.env['ir.attachment'].with_user(token['user'])
        attachment = attachments.browse([attachment_id]).exists()
        if attachment is None:
            return request.not_found()
        try:
            attachment = attachment.ensure_one()
            if attachment is None:
                return request.not_found()
        except Exception as e:
            # If the file disappear or something an exception is raised.
            # Return not found.
            return request.not_found()

        attr = attachment.read(['file_size', 'name', 'write_date'])[0]

        can_read = attachment.has_access('read')
        if not can_read:
            return request.make_response(data="Permission denied.", status=403)
        can_write = attachment.has_access('write')
        if not token['can_write']:
            can_write = False
        user_name = token['user'].display_name
        email = token['user'].email
        web_root = request.env['ir.config_parameter'].sudo().get_param('cool_wopi_host_url')
        res = {
            'BaseFileName': attr['name'],
            'Size': attr['file_size'],
            'LastModifiedTime': attr['write_date'].isoformat(),
            'UserId': token['user_id'],
            'UserFriendlyName': user_name,
            'UserCanWrite': can_write,
            'UserCanNotWriteRelative': True,
            'UserExtraInfo': {
                'avatar': '{}/web/image?model=res.users&field=avatar_128&id={}'.format(web_root, token['user_id']),
                'mail': email,
            },
            'IsAdminUser': True,
            'IsAnonymousUser': False,
        }
        return request.make_json_response(
            data=res,
            status=200,
        )

    def get_file_content(self, attachment_id, user):
        attachments = request.env['ir.attachment'].with_user(user)
        try:
            attachment = attachments.browse([attachment_id]).exists().ensure_one()
            if attachment is None:
                return request.not_found()
        except Exception as e:
            # If the file disappear or something an exception is raised.
            # Return not found.
            return request.not_found()

        if not attachment.has_access('read'):
            return request.make_response("Permission denied.", status=403)

        stream = request.env["ir.binary"]._get_stream_from(attachment, "raw", None, "name", None)
        return stream.get_response(**{"max_age": None})

    def put_file_content(self, attachment_id, user):
        attachments = request.env['ir.attachment'].with_user(user)
        try:
            attachment = attachments.browse([attachment_id]).exists().ensure_one()
            if attachment is None:
                return request.not_found()
        except Exception as e:
            # If the file disappear or something an exception is raised.
            # Return not found.
            return request.not_found()

        if not attachment.has_access('write'):
            return request.make_response("Permission denied.", status=403)

        attributes = attachment.read(['mimetype', 'write_date'])[0]
        cool_timestamp = request.httprequest.headers.get('X-COOL-WOPI-Timestamp')
        if cool_timestamp:
            try:
                cool_timestamp = datetime.datetime.fromisoformat(cool_timestamp);
            except:
                cool_timestamp = None
        if cool_timestamp and attributes['write_date'] != cool_timestamp:
            res = {
                'COOLStatusCode': 1010
            }
            return request.make_json_response(
                data=res,
                status=409,
            )


        attachment.write({"raw": request.httprequest.get_data(as_text=False), "mimetype": attributes['mimetype']})

        attributes = attachment.read(['write_date'])[0]

        res = {
            'LastModifiedTime': attributes['write_date'].isoformat(),
        }

        return request.make_json_response(
            data=res,
            status=200,
        )

    # CSRF is disabled as this uses the access_token to authenticate
    @http.route('/collabora_odoo/wopi/files/<int:attachment_id>/contents', auth='public', methods=["GET", "POST"], csrf=False)
    def file_content(self, attachment_id, access_token, access_token_ttl=0):
        token = jwt.verify_token(request, access_token)
        if 'error' in token:
            return request.make_response(data="Permission denied: {}".format(token['error']), status=401)

        if token['attachment_id'] != attachment_id:
            return request.make_response("Permission denied. Token invalid for file.", status=403)

        if request.httprequest.method == "GET":
            return self.get_file_content(attachment_id, token['user'])
        elif request.httprequest.method == "POST":
            if token['can_write'] != True:
                return request.make_response("Permission denied.", status=403)
            return self.put_file_content(attachment_id, token['user'])
        else:
            return request.make_response(data="Error, invalid method.", status=500)

    @http.route('/collabora_odoo/frame/<int:attachment_id>/<string:mode>', auth='user', website=True)
    def cool_frame(self, attachment_id, mode):
        if mode == 'write':
            write = True
        else:
            write = False

        attachments = request.env['ir.attachment']
        attachment = attachments.browse([attachment_id]).exists()
        if attachment is None:
            return request.not_found()
        try:
            attachment = attachment.ensure_one()
            if attachment is None:
                return request.not_found()
        except Exception as e:
            # If the file disappear or something an exception is raised.
            # Return not found.
            return request.not_found()

        attributes = attachment.read(['name', 'mimetype'])[0]
        want_write = write and attachment.has_access('write')

        access_token_ttl = int(request.env["ir.config_parameter"].sudo().get_param('cool_jwt_ttl'))
        if access_token_ttl == 0:
            access_token_ttl = 86400
        access_token_ttl = int(time.time()) + access_token_ttl

        user_id = request.env.user.id
        token_data = jwt.make_token(request, user_id, attachment_id, access_token_ttl, want_write)

        if 'error' in token_data:
            return request.make_response(data="Error: {}".format(token_data['error']), status=500)
        if 'token' not in token_data:
            return request.make_response(data="Error, missing token.", status=500)

        access_token = token_data['token']
        wopi_src = request.env["ir.config_parameter"].sudo().get_param('cool_wopi_host_url')
        wopi_src += "/collabora_odoo/wopi/files/" + str(attachment_id)
        try:
            config = request.env["ir.config_parameter"].sudo()
            disable_verify_cert = bool(config.get_param('cool_disable_cert_check'))
            wopi_client = discover.collabora_url(config.get_param('cool_public_url'), attributes['mimetype'],
                                                 disable_verify_cert)
        except Exception as e:
            return request.make_response(data="Error getting discovery file: {}.".format(e), status=500)

        return request.render("collabora_odoo.cool_frame", {
            "attachment_id": str(attachment_id),
            "access_token": access_token,
            "access_token_ttl": str(access_token_ttl * 1000),
            "closebutton": "false",
            "iframe_style": "",
            "wopi_client": wopi_client,
            "wopi_src": urllib.parse.quote_plus(wopi_src),
            "page_title":  attributes['name'],
        })
