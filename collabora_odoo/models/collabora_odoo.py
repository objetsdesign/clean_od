# -*- coding: utf-8 -*-
# Copyright the Collabora Online contributors.
#
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json

from odoo import api, models

class CollaboraDoc(models.Model):
    _name = "collabora.odoo"
    _description = "Collabora Online"

    @api.model
    def can_write_doc(self, attachment_id):
        attachments = self.env['ir.attachment']
        attachment = attachments.browse([attachment_id]).exists()
        if attachment is None:
            return json.dumps({'can_write': False, 'reason': 'attachment not found'})
        try:
            attachment = attachment.ensure_one()
            if attachment is None:
                return json.dumps({'can_write': False, 'reason': 'attachment no unique'})
        except Exception as e:
            # If the file disappear or something an exception is raised.
            # Return not found.
            return json.dumps({'can_write': False, 'reason': 'exception {}'.format(e)})

        can_write = attachment.check_access('write')
        return json.dumps({'can_write': can_write, 'reason': 'check access rights'})
