# -*- coding: utf-8 -*-
# Copyright the Collabora Online contributors.
#
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import jwt

# Verify the token. Return the user and attachment_id on success
# and None on failure.
def verify_token(request, token):
    secret = request.env["ir.config_parameter"].sudo().get_param('cool_jwt_secret')
    if secret is None:
        return {
            'error': 'JWT is not configured.'
        }

    jwt_payload = None
    try:
        jwt_payload = jwt.decode(token, secret, algorithms=['HS256'])
    except Exception as e:
        return {
            'error': e
        }

    if jwt_payload is None:
        return {
            'error': 'JWT token failed to decode.'
        }

    attachment_id = jwt_payload['fid']
    if attachment_id is None:
        return {
            'error': 'Missing file.'
        }

    user_id = jwt_payload['uid']
    user = request.env["res.users"].sudo().browse(user_id).exists().ensure_one()
    if user is None:
        return {
            'error': 'User not found.'
        }

    can_write = 'wri' in jwt_payload and jwt_payload['wri']

    res = {
        'user': user,
        'user_id': user_id,
        'attachment_id': attachment_id,
        'can_write': can_write,
    }
    return res

def make_token(request, user_id, attachment_id, exp, can_write=False):
    jwt_payload = {
        'fid': attachment_id,
        'uid': user_id,
        'exp': exp,
        'wri': can_write,
    }

    secret = request.env["ir.config_parameter"].sudo().get_param('cool_jwt_secret')
    if secret is None:
        return {
            'error': 'JWT is not configured.'
        }

    try:
        token = jwt.encode(jwt_payload, secret, algorithm='HS256')
    except Exception as e:
        return {
            'error': e
        }

    return {
        'token': token
    }
