/**
 * L'application Documents (Enterprise) décide si un fichier est
 * « visualisable » avec sa propre méthode `isViewable` sur ses enregistrements
 * kanban/liste. Son code source n'étant pas public, on ne l'importe pas
 * directement (un mauvais chemin d'import casserait tout le client web).
 *
 * À la place, ce service s'exécute une fois tous les modules JS chargés,
 * parcourt les modules `@documents/...` déjà chargés, et étend toute classe
 * qui définit `isViewable` pour qu'elle accepte aussi les .docx.
 * Si Documents n'est pas installé, le service ne fait rien.
 */
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { isDocxFile } from "./docx_file_model_patch";

const patchedClasses = new WeakSet();

function isDocxRecord(record) {
    const data = record?.data && typeof record.data === "object" ? record.data : record;
    if (!data) {
        return false;
    }
    return isDocxFile(data.mimetype, data.name || data.display_name || data.filename);
}

function patchDocumentsClass(cls) {
    if (patchedClasses.has(cls)) {
        return false;
    }
    const descriptor = Object.getOwnPropertyDescriptor(cls.prototype, "isViewable");
    if (!descriptor) {
        return false;
    }
    if (typeof descriptor.value === "function") {
        patch(cls.prototype, {
            isViewable(...args) {
                return isDocxRecord(this) || super.isViewable(...args);
            },
        });
    } else if (descriptor.get) {
        patch(cls.prototype, {
            get isViewable() {
                return isDocxRecord(this) || super.isViewable;
            },
        });
    } else {
        return false;
    }
    patchedClasses.add(cls);
    return true;
}

export const documentsDocxPreviewService = {
    start() {
        const modules = globalThis.odoo?.loader?.modules;
        if (!modules) {
            return;
        }
        const patchedNames = [];
        for (const [moduleName, moduleExports] of modules) {
            if (!moduleName.startsWith("@documents/") || !moduleExports) {
                continue;
            }
            for (const [exportName, value] of Object.entries(moduleExports)) {
                if (typeof value !== "function" || !value.prototype) {
                    continue;
                }
                try {
                    if (patchDocumentsClass(value)) {
                        patchedNames.push(`${moduleName} › ${exportName}`);
                    }
                } catch (error) {
                    console.warn("[documents_docx_preview] Patch impossible :", moduleName, error);
                }
            }
        }
        if (patchedNames.length) {
            console.info("[documents_docx_preview] Aperçu .docx activé pour :", patchedNames);
        }
    },
};

registry.category("services").add("documents_docx_preview", documentsDocxPreviewService);
