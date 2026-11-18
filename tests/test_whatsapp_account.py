# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsAppAccount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "Cuenta Test WhatsApp",
                "company_id": cls.company.id,
                "phone_number_id": "100000000000001",
                "waba_id": "200000000000002",
                "graph_api_token": "EAAG_TEST_TOKEN_12345",
                "api_version": "v20.0",
                "webhook_verify_token": "secret_verify_token_xyz",
                "app_secret": "super_secret_app_key_456",
            },
        )
        cls.company.whatsapp_account_id = cls.account.id

    def test_01_account_creation_and_default(self):
        """Verifica la creación y resolución predeterminada de cuenta multi-compañía."""
        self.assertTrue(self.account.id)
        default_acc = self.env["whatsapp.account"]._get_default_account(
            company=self.company,
        )
        self.assertEqual(default_acc.id, self.account.id)

    @patch("requests.post")
    @patch("requests.get")
    def test_02_action_test_connection_success(self, mock_get, mock_post):
        """Verifica que probar conexión exitosa retorna notificación client action."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified_name": "Mi Empresa S.A.",
            "display_phone_number": "+52 55 1234 5678",
            "id": "100000000000001",
        }
        mock_get.return_value = mock_response

        res = self.account.action_test_connection()
        self.assertEqual(res["type"], "ir.actions.client")
        self.assertEqual(res["tag"], "display_notification")
        self.assertEqual(res["params"]["type"], "success")
        mock_get.assert_called_once()

    @patch("requests.get")
    def test_03_action_test_connection_failure(self, mock_get):
        """Verifica que probar conexión fallida lanza UserError con detalles de Meta."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error": {
                "message": "Invalid OAuth access token.",
                "type": "OAuthException",
                "code": 190,
            },
        }
        mock_get.return_value = mock_response

        with self.assertRaises(UserError) as cm:
            self.account.action_test_connection()
        self.assertIn("190", str(cm.exception))
        self.assertIn("Invalid OAuth access token", str(cm.exception))

    @patch("requests.get", side_effect=requests.RequestException("Timeout de red"))
    def test_04_action_test_connection_network_error(self, mock_get):
        """Verifica manejo de errores de conectividad de red."""
        with self.assertRaises(UserError) as cm:
            self.account.action_test_connection()
        self.assertIn("Timeout de red", str(cm.exception))

    @patch("requests.post")
    def test_05_upload_media_success(self, mock_post):
        """Verifica subida directa en memoria de archivo binario a Meta /media."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "media_meta_id_9999"}
        mock_post.return_value = mock_response

        dummy_pdf = b"%PDF-1.4 test binary content in memory"
        media_id = self.account.upload_media(
            "Cotizacion_001.pdf", dummy_pdf, mimetype="application/pdf",
        )
        self.assertEqual(media_id, "media_meta_id_9999")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("100000000000001/media", args[0])
        self.assertIn("file", kwargs["files"])
        self.assertEqual(kwargs["data"]["messaging_product"], "whatsapp")

    @patch("requests.post")
    def test_06_upload_media_failure(self, mock_post):
        """Verifica que error al subir a Meta /media lance UserError descriptivo."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {
                "message": "File size exceeds limit",
                "type": "OAuthException",
                "code": 100,
            },
        }
        mock_post.return_value = mock_response

        with self.assertRaises(UserError) as cm:
            self.account.upload_media("test.pdf", b"content")
        self.assertIn("File size exceeds limit", str(cm.exception))

    @patch("requests.post")
    def test_07_dispatch_whatsapp_message_success(self, mock_post):
        """Verifica despacho de mensaje a Meta API /messages y extracción de wamid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "5215512345678", "wa_id": "5215512345678"}],
            "messages": [{"id": "wamid.HBgLTEST123456789"}],
        }
        mock_post.return_value = mock_response

        payload = {
            "messaging_product": "whatsapp",
            "to": "5215512345678",
            "type": "text",
            "text": {"body": "Hola prueba"},
        }
        wamid = self.account.dispatch_whatsapp_message(payload)
        self.assertEqual(wamid, "wamid.HBgLTEST123456789")

    def test_08_res_config_settings_integration(self):
        """Verifica que Ajustes enlace correctamente con la cuenta de WhatsApp."""
        settings = self.env["res.config.settings"].create(
            {
                "whatsapp_account_id": self.account.id,
            },
        )
        self.assertEqual(settings.whatsapp_phone_number_id, "100000000000001")
        self.assertEqual(settings.whatsapp_waba_id, "200000000000002")

    @patch("requests.get")
    def test_09_action_sync_templates_from_meta(self, mock_get):
        """Verifica sincronización automática de plantillas HSM aprobadas desde Meta."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "cotizacion_meta_sync_v1",
                    "language": "es",
                    "status": "APPROVED",
                    "components": [
                        {"type": "HEADER", "format": "DOCUMENT"},
                        {"type": "BODY", "text": "Hola {{1}}, su pedido {{2}} suma {{3}}."},
                        {
                            "type": "BUTTONS",
                            "buttons": [
                                {"type": "QUICK_REPLY", "text": "Aprobar"},
                                {"type": "URL", "text": "Ver Portal", "url": "https://portal.test/{{1}}"},
                            ],
                        },
                    ],
                },
                {
                    "name": "factura_cobro_sync_v1",
                    "language": "es",
                    "status": "APPROVED",
                    "components": [
                        {"type": "BODY", "text": "Estimado {{1}}, factura {{2}} pendiente."},
                    ],
                },
                {
                    "name": "plantilla_rechazada_v1",
                    "language": "es",
                    "status": "REJECTED",
                    "components": [{"type": "BODY", "text": "No aprobada"}],
                },
            ],
        }
        mock_get.return_value = mock_response

        res = self.account.action_sync_templates()
        self.assertEqual(res["params"]["type"], "success")

        tpl_so = self.env["whatsapp.template"].search(
            [("account_id", "=", self.account.id), ("name", "=", "cotizacion_meta_sync_v1")],
            limit=1,
        )
        self.assertTrue(tpl_so)
        self.assertEqual(tpl_so.header_type, "document")
        self.assertEqual(tpl_so.model, "sale.order")
        self.assertEqual(len(tpl_so.button_ids), 2)

        tpl_inv = self.env["whatsapp.template"].search(
            [("account_id", "=", self.account.id), ("name", "=", "factura_cobro_sync_v1")],
            limit=1,
        )
        self.assertTrue(tpl_inv)
        self.assertEqual(tpl_inv.model, "account.move")

        tpl_rej = self.env["whatsapp.template"].with_context(active_test=False).search(
            [("account_id", "=", self.account.id), ("name", "=", "plantilla_rechazada_v1")],
            limit=1,
        )
        self.assertFalse(tpl_rej)

    def test_10_multi_company_isolation_and_payload_retention(self):
        """Verifica que _get_default_account no filtre cuentas de otra compañía y que el cron limpie payloads antiguos."""
        other_company = self.env["res.company"].create({"name": "Compañía Aislada Sin WhatsApp"})
        isolated_acc = self.env["whatsapp.account"]._get_default_account(company=other_company)
        self.assertFalse(isolated_acc)

        old_msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_OLD_RETENTION_TEST",
                "account_id": self.account.id,
                "sender": "16505550000",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "status": "received",
                "date": fields.Datetime.now() - timedelta(days=100),
                "raw_payload": '{"secret": "old_pii_data"}',
            },
        )
        cleaned = self.env["whatsapp.message"]._cron_cleanup_old_payloads(retention_days=90)
        self.assertGreaterEqual(cleaned, 1)
        old_msg.invalidate_recordset()
        self.assertFalse(old_msg.raw_payload)
