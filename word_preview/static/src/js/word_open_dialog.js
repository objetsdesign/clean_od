/** @odoo-module */
/**
 * Comme pour Excel (« Ouvrir avec Odoo Feuille de calcul ») : un clic sur
 * un fichier Word affiche une fenêtre proposant de l'ouvrir dans l'éditeur
 * Word d'Odoo, au lieu de la visionneuse.
 */
import { Component, useEffect } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { FileViewer } from "@web/core/file_viewer/file_viewer";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

export class WordOpenDialog extends Component {
    static template = "word_preview.WordOpenDialog";
    static components = { Dialog };
    static props = ["file", "close"];

    get name() {
        return this.props.file.name || this.props.file.filename || "";
    }
    openEditor() {
        window.location.assign(`/word_editor/open/${this.props.file.id}`);
    }
    openPreview() {
        window.open(`/word_preview/${this.props.file.id}/view`, "_blank");
        this.props.close();
    }
}

patch(FileViewer.prototype, {
    setup() {
        super.setup(...arguments);
        this.wordDialogService = useService("dialog");
        useEffect(
            (file) => {
                if (file && file.isWordPreview) {
                    // Pas de visionneuse : fenêtre « Ouvrir avec l'éditeur Word ».
                    this.close();
                    this.wordDialogService.add(WordOpenDialog, { file });
                }
            },
            () => [this.state.file]
        );
    },
});
