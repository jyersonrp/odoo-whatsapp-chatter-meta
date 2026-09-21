# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.whatsapp_chatter_meta.controllers.webhook import (
    WhatsAppWebhookController,
)


@tagged("post_install", "-at_install")
class TestWhatsAppMediaAndHealth(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.whatsapp_escalation_hours = 72
        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "Cuenta Media & Health Test",
                "company_id": cls.company.id,
                "phone_number_id": "5511999990001",
                "waba_id": "200000000099999",
                "graph_api_token": "TOKEN_MEDIA_HEALTH_TEST",
                "api_version": "v21.0",
                "webhook_verify_token": "media_health_verify_token",
                "app_secret": "media_health_secret_key",
            },
        )
        cls.company.whatsapp_account_id = cls.account.id

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente Media & Health S.A.",
                "phone": "+52 55 1234 9876",
                "country_id": cls.env.ref("base.mx").id,
            },
        )

        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "company_id": cls.company.id,
            },
        )

        cls.controller = WhatsAppWebhookController()

    def _sign_payload(self, body_bytes):
        return (
            "sha256="
            + hmac.new(
                self.account.app_secret.encode("utf-8"),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
        )

    # =========================================================================
    # Media Retrieval Tests (Feature 9, 10, 11, 12)
    # =========================================================================

    @patch("requests.get")
    def test_01_get_media_url_success(self, mock_get):
        """Verifica la consulta exitosa de URL temporal en Meta Graph API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=999",
            "mime_type": "image/jpeg",
            "file_size": 102400,
            "id": "media_img_999",
        }
        mock_get.return_value = mock_resp

        url = self.account.get_media_url("media_img_999")
        self.assertIsInstance(url, str)
        self.assertIn("lookaside.fbsbx.com", url)
        mock_get.assert_called_once()

    @patch("requests.get")
    def test_02_get_media_url_error(self, mock_get):
        """Verifica que un error HTTP en Meta al consultar media_id lanza UserError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = '{"error": {"message": "Media not found", "code": 100}}'
        mock_resp.json.return_value = {
            "error": {"message": "Media not found", "code": 100},
        }
        mock_get.return_value = mock_resp

        with self.assertRaises(UserError):
            self.account.get_media_url("invalid_media_id")

    @patch("requests.get")
    def test_03_download_media_success(self, mock_get):
        """Verifica la descarga binaria desde Lookaside CDN con headers correctos."""
        with patch.object(
            type(self.account),
            "get_media_url",
            return_value="https://lookaside.fbsbx.com/cdn_file",
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"%PDF-1.4 Fake PDF Content"
            mock_resp.headers = {"Content-Type": "application/pdf"}
            mock_get.return_value = mock_resp

            content, mime, filename = self.account.download_media(
                "media_pdf_123",
                filename="factura.pdf",
            )
            self.assertEqual(content, b"%PDF-1.4 Fake PDF Content")
            self.assertEqual(mime, "application/pdf")
            self.assertEqual(filename, "factura.pdf")
            mock_get.assert_called_once()
            called_headers = mock_get.call_args[1].get("headers", {})
            self.assertEqual(
                called_headers.get("Authorization"),
                f"Bearer {self.account.graph_api_token}",
            )
            self.assertEqual(
                called_headers.get("User-Agent"),
                "Odoo-WhatsApp-Client/1.0",
            )

    def _mock_request(self, args=None, headers=None, data=b""):
        mock_req = MagicMock()
        mock_req.env = self.env
        mock_req.httprequest.args = args or {}
        mock_req.httprequest.headers = headers or {}
        mock_req.httprequest.get_data.return_value = data
        return mock_req

    def test_04_webhook_incoming_media_download_and_attach(self):
        """Verifica que un mensaje entrante con imagen descarga el binario y crea un ir.attachment en el Chatter."""
        fake_bytes = b"\xff\xd8\xff\xe0 Fake JPEG"
        wamid = "wamid.HBgLMEDIA_TEST_001"

        with patch.object(
            type(self.account),
            "download_media",
            return_value=(fake_bytes, "image/jpeg", "comprobante_pago.jpg"),
        ):
            payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {
                                        "phone_number_id": self.account.phone_number_id,
                                    },
                                    "contacts": [
                                        {
                                            "wa_id": "525512349876",
                                            "profile": {"name": "Cliente Media S.A."},
                                        },
                                    ],
                                    "messages": [
                                        {
                                            "from": "525512349876",
                                            "id": wamid,
                                            "type": "image",
                                            "image": {
                                                "id": "meta_media_id_777",
                                                "mime_type": "image/jpeg",
                                                "caption": "Aquí envío mi comprobante",
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            }
            body_bytes = json.dumps(payload).encode("utf-8")
            signature = self._sign_payload(body_bytes)

            mock_req = self._mock_request(
                headers={"X-Hub-Signature-256": signature},
                data=body_bytes,
            )
            with patch(
                "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
                new=mock_req,
            ):
                res = self.controller.webhook_receive()
                self.assertEqual(res.status_code, 200)

            # Verificar creación de whatsapp.message con attachment_id y media_id
            msg_rec = self.env["whatsapp.message"].search(
                [("wamid", "=", wamid)],
                limit=1,
            )
            self.assertTrue(msg_rec.exists())
            self.assertEqual(msg_rec.media_id, "meta_media_id_777")
            self.assertTrue(msg_rec.attachment_id)
            self.assertEqual(msg_rec.attachment_id.name, "comprobante_pago.jpg")
            self.assertEqual(msg_rec.attachment_id.raw, fake_bytes)

            # Verificar adjunto en el Chatter de la orden abierta del partner
            self.assertEqual(msg_rec.res_model, "sale.order")
            self.assertEqual(msg_rec.res_id, self.sale_order.id)

    def test_05_webhook_incoming_media_download_resilient_fallback(self):
        """Verifica que si la descarga de Meta falla, el webhook responde 200 y registra nota con error."""
        wamid = "wamid.HBgLMEDIA_FAIL_002"

        with patch.object(
            type(self.account),
            "download_media",
            side_effect=UserError("Timeout al conectar con Meta CDN"),
        ):
            payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {
                                        "phone_number_id": self.account.phone_number_id,
                                    },
                                    "contacts": [
                                        {
                                            "wa_id": "525512349876",
                                            "profile": {"name": "Cliente Media S.A."},
                                        },
                                    ],
                                    "messages": [
                                        {
                                            "from": "525512349876",
                                            "id": wamid,
                                            "type": "document",
                                            "document": {
                                                "id": "meta_doc_fail_888",
                                                "filename": "archivo_grande.pdf",
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            }
            body_bytes = json.dumps(payload).encode("utf-8")
            signature = self._sign_payload(body_bytes)

            mock_req = self._mock_request(
                headers={"X-Hub-Signature-256": signature},
                data=body_bytes,
            )
            with patch(
                "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
                new=mock_req,
            ):
                res = self.controller.webhook_receive()
                # No debe devolver 500; debe mantener 200 OK hacia Meta
                self.assertEqual(res.status_code, 200)

            msg_rec = self.env["whatsapp.message"].search(
                [("wamid", "=", wamid)],
                limit=1,
            )
            self.assertTrue(msg_rec.exists())
            self.assertEqual(msg_rec.media_id, "meta_doc_fail_888")
            self.assertFalse(msg_rec.attachment_id)

    # =========================================================================
    # Conversation Health & Window State Tests (Feature 13, 14, 15)
    # =========================================================================

    def test_06_health_state_none_without_messages(self):
        """Un pedido nuevo sin mensajes tiene estado 'none'."""
        self.sale_order._compute_whatsapp_health_state()
        self.assertEqual(self.sale_order.whatsapp_health_state, "none")

    def test_07_health_state_active_with_recent_inbound(self):
        """Un pedido con mensaje entrante hace 2 horas tiene estado 'active'."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HEALTH_INBOUND_RECENT",
                "account_id": self.account.id,
                "sender": "+525512349876",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "received",
                "date": fields.Datetime.now() - timedelta(hours=2),
            },
        )

        self.sale_order._compute_whatsapp_health_state()
        self.assertEqual(self.sale_order.whatsapp_health_state, "active")

    def test_08_health_state_expired_with_single_recent_outbound(self):
        """Un pedido con un solo mensaje saliente enviado hace 5h sin respuesta tiene estado 'expired'."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HEALTH_OUTBOUND_EXPIRED",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+525512349876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": fields.Datetime.now() - timedelta(hours=5),
            },
        )

        self.sale_order._compute_whatsapp_health_state()
        self.assertEqual(self.sale_order.whatsapp_health_state, "expired")

    def test_09_health_state_cold_with_multiple_consecutive_outbounds(self):
        """Un pedido con 2 mensajes salientes consecutivos sin respuesta tiene estado 'cold'."""
        now = fields.Datetime.now()
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HEALTH_OUTBOUND_1",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+525512349876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": now - timedelta(hours=10),
            },
        )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HEALTH_OUTBOUND_2",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+525512349876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": now - timedelta(hours=2),
            },
        )

        self.sale_order._compute_whatsapp_health_state()
        self.assertEqual(self.sale_order.whatsapp_health_state, "cold")

    def test_10_health_state_cold_stale_over_threshold(self):
        """Un mensaje saliente con más de 72 horas sin respuesta marca el hilo como 'cold'."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HEALTH_OUTBOUND_STALE_80H",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+525512349876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": fields.Datetime.now() - timedelta(hours=80),
            },
        )

        self.sale_order._compute_whatsapp_health_state()
        self.assertEqual(self.sale_order.whatsapp_health_state, "cold")
