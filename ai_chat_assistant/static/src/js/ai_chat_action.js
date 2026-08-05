/** @odoo-module **/

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AiChatAction extends Component {
    static template = "ai_chat_assistant.ChatAction";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            sessionId: null,
            messages: [], // { role: 'user'|'assistant', body: string }
            draft: "",
            sending: false,
        });
        this.messagesRef = useRef("messagesList");

        onMounted(async () => {
            const [session] = await this.orm.create("ai.chat.session", [{}]);
            this.state.sessionId = session;
            this.state.messages.push({
                role: "assistant",
                body: "Bonjour 👋 Posez-moi une question sur vos factures, devis, " +
                      "commandes d'achat ou votre stock. Ex: « Quel est le stock du " +
                      "produit ABC ? » ou « Liste les factures impayées de la société X ».",
            });
        });
    }

    async scrollToBottom() {
        await new Promise((r) => setTimeout(r, 0));
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onInput(ev) {
        this.state.draft = ev.target.value;
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    async sendMessage() {
        const body = this.state.draft.trim();
        if (!body || this.state.sending || !this.state.sessionId) {
            return;
        }
        this.state.draft = "";
        this.state.messages.push({ role: "user", body });
        this.state.sending = true;
        await this.scrollToBottom();

        try {
            const res = await this.orm.call(
                "ai.chat.session",
                "send_message",
                [[this.state.sessionId], body]
            );
            this.state.messages.push({
                role: "assistant",
                body: (res && res.body) || "(pas de réponse)",
            });
        } catch (e) {
            this.state.messages.push({
                role: "assistant",
                body: "⚠️ Une erreur est survenue: " + (e.message || e),
            });
        } finally {
            this.state.sending = false;
            await this.scrollToBottom();
        }
    }
}

registry.category("actions").add("ai_chat_assistant.ChatAction", AiChatAction);
