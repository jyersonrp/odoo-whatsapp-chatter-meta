# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "WhatsApp Chatter Integration (Meta Cloud API)",
    "version": "19.0.1.0.0",
    "category": "Sales/Marketing",
    "summary": "Direct Meta WhatsApp Cloud API Integration for Odoo Chatter with Bilingual (EN/ES) Support",
    "description": """
WhatsApp Cloud API Integration for Odoo Chatter (Meta Graph API v21.0+)
========================================================================
Enterprise-grade bidirectional WhatsApp integration for Quotations, Invoices, and Contacts.

Key Features:
-------------
- Full Bilingual Support (i18n): Standard Odoo translations for English (en_US) and Spanish (es, es_ES).
- Header Action Button: "Send via WhatsApp" on sale.order and account.move launching a dynamic composer wizard.
- In-Memory PDF Compilation: Generates quotation/invoice PDFs using ir.actions.report._render_qweb_pdf() and uploads directly to Meta Cloud API (/media) without temporary disk files.
- Dynamic 24-Hour Window Validation: Distinguishes between active 24-hour service conversations (freeform text allowed) and expired windows (Meta HSM templates required).
- High-Security Webhook (/whatsapp/webhook):
  * GET verification handshake with hub.verify_token and hub.challenge.
  * POST cryptographic validation using HMAC-SHA256 (X-Hub-Signature-256) against Meta App Secret.
  * Automatic thread correlation (context.id / wamid) linking replies to the active document Chatter.
  * Real-time message status updates (sent, delivered, read, failed).
- Multi-Company Management: Dedicated WhatsApp accounts configurable per company with default fallback in Settings.
- Message Audit Log: Full historical tracking with raw Meta JSON payloads for complete observability.
    """,
    "author": "Yerson R.",
    "depends": [
        "base",
        "mail",
        "sale",
        "account",
        "phone_validation",
    ],
    "data": [
        "security/whatsapp_security.xml",
        "security/ir.model.access.csv",
        "data/whatsapp_cron_data.xml",
        "views/whatsapp_account_views.xml",
        "views/whatsapp_template_views.xml",
        "views/whatsapp_message_views.xml",
        "views/res_config_settings_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "wizard/whatsapp_composer_wizard_views.xml",
        "views/whatsapp_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
