/** @odoo-module **/
/* -*- js-indent-level: 4 -*- */
/*
 * Copyright the Collabora Online contributors.
 *
 * SPDX-License-Identifier: MPL-2.0
 *
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */

import { AttachmentList } from "@mail/core/common/attachment_list";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

const cool_extensions = [
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "odt", "ods", "odp", "odg",
];

patch(AttachmentList.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    },

    isCoolAttachment(attachment) {
        return cool_extensions.includes(attachment.extension.toLowerCase());
    },

    async canWrite(attachment) {
        if (!attachment || !this.isCoolAttachment(attachment)) {
            return false;
        }
        let result = await this.orm.call("collabora.odoo", "can_write_doc", [attachment.id]);
        if (result?.reason) {
            console.error("can write error", result.reason);
        }
        return result?.can_write;
    },

    coolOpen(attachment, mode) {
        // Any other value is "read"
        switch (mode) {
        case 'read':
        case 'write':
            break;
        default:
            mode = 'read';
        }
        console.log(`coolOpen called to open ${attachment.id}`);
        window.open(`/collabora_odoo/frame/${attachment.id}/${mode}`, "_blank");
    }
});
