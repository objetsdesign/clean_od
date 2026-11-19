# -*- coding: utf-8 -*-
# Copyright the Collabora Online contributors.
#
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests
from lxml import etree

def collabora_url(server, mime_type, disable_verify_cert=False):
    #
    # WARNING: `disable_verify_cert` should never be `True` on a production server.
    # This is only done to allow the use of self signed certificates on the Collabora
    # Online server for example purpose.
    #

    response = requests.get(server + '/hosting/discovery', verify=not disable_verify_cert)
    discovery = response.text
    if not discovery:
        raise Exception('Not able to retrieve the discovery.xml file from the Collabora Online server with the submitted address.')
        return
    # print(discovery)
    parsed = etree.fromstring(discovery)
    if parsed is None:
        raise Exception('The retrieved discovery.xml file is not a valid XML file')
        return
    result = parsed.xpath(f"/wopi-discovery/net-zone/app[@name='{mime_type}']/action")
    if len(result) < 1:
        raise Exception('The requested mime type is not handled')
        return
    online_url = result[0].get('urlsrc')
    #print('online url: ' + online_url)
    return online_url
