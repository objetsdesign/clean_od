/** @odoo-module */
/**
 * Aperçu Word : les fichiers .docx / .doc / .odt / .rtf deviennent
 * « visualisables » dans la visionneuse d'Odoo. Ils sont affichés comme un
 * document Word (pages, mise en page) via /word_preview/<id>/view.
 * Le téléchargement reste celui du fichier Word d'origine.
 */
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";
import { FileModel } from "@web/core/file_viewer/file_model";
import { Attachment } from "@mail/core/common/attachment_model";

const WORD_MIMETYPES = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "application/vnd.ms-word.document.macroenabled.12",
    "application/msword",
    "application/vnd.oasis.opendocument.text",
    "application/rtf",
    "text/rtf",
];
const WORD_EXTENSIONS = ["docx", "doc", "odt", "rtf", "docm", "dotx", "dot"];

const wordPreviewPatch = {
    get isWordPreview() {
        if (this.type === "url" || !this.id || this.id < 0) {
            return false;
        }
        const name = this.name || this.filename || "";
        const ext = (this.extension || name.split(".").pop() || "").toLowerCase();
        return WORD_MIMETYPES.includes(this.mimetype) || WORD_EXTENSIONS.includes(ext);
    },
    get isPdf() {
        return super.isPdf || this.isWordPreview;
    },
    get isViewable() {
        return super.isViewable || (this.isWordPreview && !this.uploading);
    },
    get defaultSource() {
        if (this.isWordPreview) {
            const params = this.access_token ? { access_token: this.access_token } : {};
            // Page d'aperçu « façon Word » (pages blanches, mise en page Word)
            return url(`/word_preview/${this.id}/view`, params);
        }
        return super.defaultSource;
    },
};

patch(FileModel.prototype, wordPreviewPatch);
patch(Attachment.prototype, wordPreviewPatch);
