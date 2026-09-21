# Part of Odoo. See LICENSE file for full copyright and licensing details.

import pathlib

import polib

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsAppI18n(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module_dir = pathlib.Path(__file__).resolve().parent.parent
        cls.i18n_dir = cls.module_dir / "i18n"
        cls.pot_file = cls.i18n_dir / "whatsapp_chatter_meta.pot"
        cls.en_po_file = cls.i18n_dir / "en_US.po"
        cls.es_po_file = cls.i18n_dir / "es.po"
        cls.es_es_po_file = cls.i18n_dir / "es_ES.po"

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "I18n Test Partner",
                "phone": "+16505550199",
            },
        )
        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
            },
        )

    def test_01_i18n_files_exist(self):
        """Verify that all standard i18n translation files exist in i18n/."""
        self.assertTrue(self.i18n_dir.is_dir(), "The i18n directory must exist.")
        self.assertTrue(self.pot_file.is_file(), "whatsapp_chatter_meta.pot must exist.")
        self.assertTrue(self.en_po_file.is_file(), "en_US.po must exist.")
        self.assertTrue(self.es_po_file.is_file(), "es.po must exist.")
        self.assertTrue(self.es_es_po_file.is_file(), "es_ES.po must exist.")

    def test_02_pot_file_valid_and_non_empty(self):
        """Verify that the POT file is syntactically valid and has English msgids."""
        pot = polib.pofile(str(self.pot_file), encoding="utf-8")
        self.assertGreater(len(pot), 50, "The POT file must contain at least 50 terms.")

        msgids = {entry.msgid for entry in pot if entry.msgid}
        self.assertIn("Active Window", msgids)
        self.assertIn("Expired Window", msgids)
        self.assertIn("Cold Thread", msgids)
        self.assertIn("No Conversation", msgids)
        self.assertIn("Send via WhatsApp", msgids)
        self.assertIn("Official Meta Template (HSM)", msgids)
        self.assertIn("WhatsApp Accounts", msgids)
        self.assertIn("Message Logs", msgids)

    def test_03_es_translations_mapping(self):
        """Verify Spanish translations (English msgid -> Spanish msgstr)."""
        po_es = polib.pofile(str(self.es_po_file), encoding="utf-8")
        translations = {entry.msgid: entry.msgstr for entry in po_es if entry.msgid}

        expected_pairs = {
            "Active Window": "Ventana Activa",
            "Expired Window": "Ventana Expirada",
            "Cold Thread": "Hilo Frío",
            "No Conversation": "Sin Conversación",
            "Send via WhatsApp": "Enviar por WhatsApp",
            "Send Quotation via WhatsApp": "Enviar Cotización por WhatsApp",
            "Send Invoice via WhatsApp": "Enviar Factura por WhatsApp",
            "Connection Successful": "Conexión Exitosa",
            "WhatsApp Dispatched": "WhatsApp Despachado",
            "WhatsApp Accounts": "Cuentas de WhatsApp",
            "Message Logs": "Bitácora de Mensajes",
            "Official Templates (HSM)": "Plantillas Oficiales (HSM)",
            "Configuration": "Configuración",
            "Test Connection": "Probar Conexión",
            "Outbound": "Saliente",
            "Inbound": "Entrante",
            "Text": "Texto",
            "Document": "Documento",
            "Draft": "Borrador",
            "Sent": "Enviado",
            "Delivered": "Entregado",
            "Read": "Leído",
            "Failed": "Fallido",
            "Received": "Recibido",
        }

        for en_term, es_term in expected_pairs.items():
            self.assertIn(en_term, translations, f"Term '{en_term}' must be in es.po")
            self.assertEqual(
                translations[en_term],
                es_term,
                f"Spanish translation of '{en_term}' must be '{es_term}'",
            )

    def test_04_po_files_completeness(self):
        """Verify that translation files have no untranslated entries."""
        for po_path in (self.es_po_file, self.es_es_po_file, self.en_po_file):
            po = polib.pofile(str(po_path), encoding="utf-8")
            self.assertGreater(len(po), 50, f"{po_path.name} must contain terms.")
            untranslated = [e.msgid for e in po if e.msgid and not e.msgstr]
            self.assertEqual(
                len(untranslated),
                0,
                f"No untranslated terms should exist in {po_path.name}: {untranslated[:5]}",
            )

    def test_05_runtime_selection_field_i18n(self):
        """Verify that selection options switch labels between en_US and es_ES in runtime."""
        # In en_US
        env_en = self.env(context=dict(self.env.context, lang="en_US"))
        selection_en = dict(
            self.sale_order.with_env(env_en)._fields["whatsapp_health_state"]._description_selection(env_en),
        )
        self.assertEqual(selection_en.get("active"), "Active Window")
        self.assertEqual(selection_en.get("expired"), "Expired Window")
        self.assertEqual(selection_en.get("cold"), "Cold Thread")
        self.assertEqual(selection_en.get("none"), "No Conversation")

        # In es_ES
        lang_es = self.env["res.lang"].search([("code", "=", "es_ES")], limit=1)
        if lang_es:
            env_es = self.env(context=dict(self.env.context, lang="es_ES"))
            selection_es = dict(
                self.sale_order.with_env(env_es)._fields["whatsapp_health_state"]._description_selection(env_es),
            )
            self.assertEqual(selection_es.get("active"), "Ventana Activa")
            self.assertEqual(selection_es.get("expired"), "Ventana Expirada")
            self.assertEqual(selection_es.get("cold"), "Hilo Frío")
            self.assertEqual(selection_es.get("none"), "Sin Conversación")

    def test_06_runtime_translation_gettext(self):
        """Verify that _() function returns English in en_US and Spanish in es_ES context."""
        env_en = self.env(context=dict(self.env.context, lang="en_US"))
        msg_en = env_en._("Connection Successful")
        self.assertEqual(msg_en, "Connection Successful")

        lang_es = self.env["res.lang"].search([("code", "=", "es_ES")], limit=1)
        if lang_es:
            env_es = self.env(context=dict(self.env.context, lang="es_ES"))
            msg_es = env_es._("Connection Successful")
            self.assertEqual(msg_es, "Conexión Exitosa")
