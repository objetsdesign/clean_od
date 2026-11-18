import { FileModel } from "@web/core/file_viewer/file_model";
import { Attachment } from "@mail/core/common/attachment_model";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";

export const DOCX_MIMETYPES = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

const VIEWER_PATH = "/documents_docx_preview/static/src/viewer/docx_viewer.html";

/**
 * @param {string} [mimetype]
 * @param {string} [name]
 * @returns {boolean}
 */
export function isDocxFile(mimetype, name) {
    if (mimetype && DOCX_MIMETYPES.includes(mimetype)) {
        return true;
    }
    return typeof name === "string" && /\.docx$/i.test(name.trim());
}

/**
 * Extension commune à tous les modèles de fichiers (FileModel du web et
 * Attachment de mail) : déclare le .docx comme « visualisable » et renvoie
 * l'URL de la page de rendu docx.
 */
const docxFileModelExtension = {
    get isDocx() {
        return isDocxFile(this.mimetype, this.name || this.filename);
    },

    get isViewable() {
        return (this.isDocx && !this.uploading) || super.isViewable;
    },

    get defaultSource() {
        if (this.isDocx) {
            const route = url(this.urlRoute, this.urlQueryParams);
            return `${VIEWER_PATH}?file=${encodeURIComponent(route)}`;
        }
        return super.defaultSource;
    },
};

patch(FileModel.prototype, docxFileModelExtension);
patch(Attachment.prototype, docxFileModelExtension);
