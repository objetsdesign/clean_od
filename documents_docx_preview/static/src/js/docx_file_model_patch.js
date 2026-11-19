import { FileModel } from "@web/core/file_viewer/file_model";
import { Attachment } from "@mail/core/common/attachment_model";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";

export const DOCX_MIMETYPE =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const VIEWER_PATH = "/documents_docx_preview/static/src/viewer/docx_viewer.html";

/**
 * @param {string} [mimetype]
 * @param {string} [name]
 * @returns {boolean}
 */
export function isDocxFile(mimetype, name) {
    if (mimetype === DOCX_MIMETYPE) {
        return true;
    }
    return typeof name === "string" && /\.docx$/i.test(name.trim());
}

/**
 * URL de la page de rendu. Plusieurs liens possibles : la page essaie
 * chacun dans l'ordre jusqu'à ce qu'un fonctionne.
 * @param {string[]} fileUrls
 */
export function buildDocxViewerUrl(fileUrls) {
    const query = fileUrls.map((u) => `file=${encodeURIComponent(u)}`).join("&");
    return `${VIEWER_PATH}?${query}`;
}

/**
 * Pièces jointes (chatter, champs fichiers) : déclare le .docx comme
 * « visualisable » et renvoie l'URL de la page de rendu.
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
            return buildDocxViewerUrl([url(this.urlRoute, this.urlQueryParams)]);
        }
        return super.defaultSource;
    },
};

patch(FileModel.prototype, docxFileModelExtension);
patch(Attachment.prototype, docxFileModelExtension);
