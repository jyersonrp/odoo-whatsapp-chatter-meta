# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.whatsapp_chatter_meta.controllers.webhook import (
    WhatsAppWebhookController,
)


@tagged("post_install", "-at_install")
class TestWhatsAppWebhook(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = WhatsAppWebhookController()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente WhatsApp",
                "phone": "+16505559876",
            },
        )
        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "Cuenta Webhook Test",
                "company_id": cls.company.id,
                "phone_number_id": "109999999999999",
                "waba_id": "209999999999999",
                "graph_api_token": "EAAG_WEBHOOK_TOKEN",
                "webhook_verify_token": "test_verify_token_123",
                "app_secret": "super_secret_meta_app_secret_abc",
            },
        )
        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "state": "draft",
            },
        )

    def _sign_payload(self, payload_bytes, secret=None):
        secret = secret or self.account.app_secret
        sig_hash = hmac.new(
            secret.encode("utf-8"), payload_bytes, hashlib.sha256,
        ).hexdigest()
        return f"sha256={sig_hash}"

    def _mock_request(self, args=None, headers=None, data=b""):
        mock_req = MagicMock()
        mock_req.env = self.env
        mock_req.httprequest.args = args or {}
        mock_req.httprequest.headers = headers or {}
        mock_req.httprequest.get_data.return_value = data
        return mock_req

    # -------------------------------------------------------------
    # GET Handshake Verification Tests
    # -------------------------------------------------------------
    def test_01_get_handshake_success(self):
        """Verifica que el handshake GET con verify_token correcto responde con hub.challenge y HTTP 200."""
        mock_request = self._mock_request(
            args={
                "hub.mode": "subscribe",
                "hub.verify_token": "test_verify_token_123",
                "hub.challenge": "CHALLENGE_STRING_789456",
            },
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_request,
        ):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.response[0].decode("utf-8"), "CHALLENGE_STRING_789456",
            )

    def test_02_get_handshake_invalid_token(self):
        """Verifica que un token de verificación incorrecto sea rechazado con HTTP 403."""
        mock_request = self._mock_request(
            args={
                "hub.mode": "subscribe",
                "hub.verify_token": "token_incorrecto",
                "hub.challenge": "CHALLENGE_STRING_789456",
            },
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_request,
        ):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 403)

    def test_03_get_handshake_invalid_mode(self):
        """Verifica que un modo distinto a 'subscribe' sea rechazado con HTTP 403."""
        mock_request = self._mock_request(
            args={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "test_verify_token_123",
                "hub.challenge": "CHALLENGE_STRING_789456",
            },
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_request,
        ):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 403)

    # -------------------------------------------------------------
    # POST HMAC-SHA256 Signature Verification Tests
    # -------------------------------------------------------------
    def test_04_post_signature_validation(self):
        """Verifica la validación criptográfica de la firma HMAC-SHA256 del Webhook."""
        payload_data = {"entry": []}
        raw_body = json.dumps(payload_data).encode("utf-8")
        valid_sig = self._sign_payload(raw_body)
        invalid_sig = (
            "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        )

        # Caso 1: Firma correcta -> 200
        mock_req_valid = self._mock_request(
            headers={"X-Hub-Signature-256": valid_sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req_valid,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Caso 2: Firma incorrecta -> 403
        mock_req_invalid = self._mock_request(
            headers={"X-Hub-Signature-256": invalid_sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req_invalid,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 403)

        # Caso 3: Sin firma en cabecera -> 403
        mock_req_nosig = self._mock_request(headers={}, data=raw_body)
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req_nosig,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 403)

    # -------------------------------------------------------------
    # Inbound Message Correlation Tests
    # -------------------------------------------------------------
    def test_05_incoming_message_with_context_id(self):
        """
        Verifica que si el cliente cita o responde a un mensaje previo (context.id),
        la respuesta se publique exactamente en el Chatter del documento original vinculado.
        """
        outbound_wamid = "wamid.HBgL_ORIGINAL_OUTBOUND_1001"
        self.env["whatsapp.message"].create(
            {
                "wamid": outbound_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
            },
        )

        incoming_wamid = "wamid.HBgL_REPLY_INBOUND_2002"
        incoming_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "text",
                                        "text": {
                                            "body": "Acepto la cotización, procedan.",
                                        },
                                        "context": {"id": outbound_wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Verificar que se publicó en el Chatter de self.sale_order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        latest_msg = self.sale_order.message_ids[0]
        self.assertIn("Acepto la cotización, procedan", latest_msg.body)
        self.assertIn(incoming_wamid, latest_msg.body)

        # Verificar registro en bitácora whatsapp.message
        inbound_log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertTrue(inbound_log)
        self.assertEqual(inbound_log.direction, "inbound")
        self.assertEqual(inbound_log.res_model, "sale.order")
        self.assertEqual(inbound_log.res_id, self.sale_order.id)

    def test_06_incoming_unquoted_message_correlates_latest_open_document(self):
        """
        Verifica que un mensaje nuevo sin contexto se asocie al último documento abierto
        del contacto y se inserte en su Chatter.
        """
        incoming_wamid = "wamid.HBgL_UNQUOTED_INBOUND_3003"
        incoming_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "text",
                                        "text": {
                                            "body": "Hola, ¿cuándo me entregan el pedido?",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Debe asociarse automáticamente al pedido abierto self.sale_order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        latest_msg = self.sale_order.message_ids[0]
        self.assertIn("¿cuándo me entregan el pedido?", latest_msg.body)

    # -------------------------------------------------------------
    # Delivery Status Updates Tests
    # -------------------------------------------------------------
    def test_07_status_failed_alerts_in_chatter(self):
        """
        Verifica que al recibir un evento status == 'failed', se actualice la bitácora
        y se publique una advertencia de rechazo en el Chatter.
        """
        tracked_wamid = "wamid.HBgL_TRACKED_OUTBOUND_4004"
        wa_msg = self.env["whatsapp.message"].create(
            {
                "wamid": tracked_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
            },
        )

        status_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "statuses": [
                                    {
                                        "id": tracked_wamid,
                                        "status": "failed",
                                        "timestamp": "1725559999",
                                        "recipient_id": "16505559876",
                                        "errors": [
                                            {
                                                "code": 131026,
                                                "title": "Message Undeliverable",
                                                "message": "Recipient phone number not on WhatsApp",
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(status_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # 1. Comprobar que el estado de whatsapp.message pasó a 'failed' y tiene error_code
        wa_msg.invalidate_recordset()
        self.assertEqual(wa_msg.status, "failed")
        self.assertEqual(wa_msg.error_code, "131026")
        self.assertIn("131026", wa_msg.error_message)
        self.assertIn("Recipient phone number not on WhatsApp", wa_msg.error_message)

        # 2. Comprobar alerta publicada en el Chatter de sale.order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        alert_msg = self.sale_order.message_ids[0]
        self.assertIn("WhatsApp delivery failure", alert_msg.body)
        self.assertIn("131026", alert_msg.body)

    def test_08_status_delivered_updates_message_status(self):
        """Verifica que evento de estado delivered actualice whatsapp.message."""
        tracked_wamid = "wamid.HBgL_TRACKED_OUTBOUND_5005"
        wa_msg = self.env["whatsapp.message"].create(
            {
                "wamid": tracked_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
            },
        )

        status_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "statuses": [
                                    {
                                        "id": tracked_wamid,
                                        "status": "delivered",
                                        "timestamp": "1725559999",
                                        "recipient_id": "16505559876",
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(status_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        wa_msg.invalidate_recordset()
        self.assertEqual(wa_msg.status, "delivered")

    def test_09_webhook_idempotency_duplicate_message(self):
        """Verifica que mensajes con el mismo wamid no se publiquen dos veces en Chatter ni en bitácora."""
        incoming_wamid = "wamid.HBgL_DUPLICATE_IDEMPOTENCY_7007"
        incoming_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "text",
                                        "text": {
                                            "body": "Mensaje que se entrega dos veces por reintento de Meta",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            # Primera entrega
            resp1 = self.controller.webhook_receive()
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)

            # Segunda entrega (duplicada de Meta)
            resp2 = self.controller.webhook_receive()
            self.assertEqual(resp2.status_code, 200)
            # El conteo de mensajes en Chatter no debe aumentar
            self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)

        # En la bitácora debe existir un único registro
        logs = self.env["whatsapp.message"].search([("wamid", "=", incoming_wamid)])
        self.assertEqual(len(logs), 1)

    def test_10_webhook_unknown_message_type_handling(self):
        """Verifica que tipos de mensajes no contemplados (ej. sticker, reaction) se registren como 'other' sin error."""
        incoming_wamid = "wamid.HBgL_UNKNOWN_TYPE_8008"
        incoming_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "reaction",
                                        "reaction": {
                                            "message_id": "wamid.xxx",
                                            "emoji": "👍",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log.message_type, "other")

    def test_11_webhook_unquoted_without_open_document_falls_back_to_partner_chatter(
        self,
    ):
        """Verifica que si no hay orden ni factura abierta, el mensaje se inserte en el Chatter del contacto."""
        partner_no_doc = self.env["res.partner"].create(
            {
                "name": "Contacto Sin Documentos",
                "phone": "+1 (650) 999-0000",
            },
        )
        incoming_wamid = "wamid.HBgL_FALLBACK_PARTNER_9009"
        incoming_payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16509990000",
                                        "profile": {"name": "Contacto Sin Documentos"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16509990000",
                                        "id": incoming_wamid,
                                        "type": "text",
                                        "text": {
                                            "body": "Hola, quiero información general.",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        initial_partner_msgs = len(partner_no_doc.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        self.assertEqual(len(partner_no_doc.message_ids), initial_partner_msgs + 1)
        self.assertIn("información general", partner_no_doc.message_ids[0].body)

    test_11_webhook_incoming_message_fallback_matching_phone = (
        test_11_webhook_unquoted_without_open_document_falls_back_to_partner_chatter
    )

    def test_12_webhook_multi_account_resolution_by_phone_number_id(self):
        """Verifica que si hay múltiples cuentas, el webhook asocie el mensaje al account_id correcto por phone_number_id."""
        account2 = self.env[
            "whatsapp.account"
        ].create(
            {
                "name": "Cuenta Secundaria",
                "company_id": self.company.id,
                "phone_number_id": "999888777666555",
                "waba_id": "209999999999999",
                "graph_api_token": "EAAG_TOKEN_2",
                "webhook_verify_token": "token_2",
                "app_secret": self.account.app_secret,  # Mismo app secret de la app de Meta
            },
        )

        incoming_wamid = "wamid.HBgL_MULTI_ACC_10010"
        incoming_payload = {
            "entry": [
                {
                    "id": account2.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": account2.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "text",
                                        "text": {
                                            "body": "Mensaje dirigido al número secundario",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(incoming_payload).encode("utf-8")
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log.account_id.id, account2.id)

    def test_13_incoming_button_reply_correlates_sale_order_and_reactivates_window(
        self,
    ):
        """Verifica que al recibir un webhook con type='button' (Quick Reply):
        1. Se correlacione vía context.id al sale.order original.
        2. Se publique la respuesta en el Chatter del pedido.
        3. Se registre en bitácora con message_type='button'.
        4. Se reactive la ventana de atención de 24 horas (_is_whatsapp_window_open).
        """
        outbound_wamid = "wamid.HBgL_SO_OUTBOUND_BTN_01"
        self.env["whatsapp.message"].create(
            {
                "wamid": outbound_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": fields.Datetime.now() - timedelta(hours=30),
            },
        )
        self.assertFalse(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        incoming_wamid = "wamid.HBgL_BTN_REPLY_INBOUND_01"
        btn_text = "Aprobar Cotización"
        btn_payload = "SO_APPROVE_PAYLOAD_101"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "timestamp": str(
                                            int(fields.Datetime.now().timestamp()),
                                        ),
                                        "type": "button",
                                        "button": {
                                            "text": btn_text,
                                            "payload": btn_payload,
                                        },
                                        "context": {"id": outbound_wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        latest_msg = self.sale_order.message_ids[0]
        self.assertIn(btn_text, latest_msg.body)
        self.assertIn(incoming_wamid, latest_msg.body)

        log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log.direction, "inbound")
        self.assertEqual(log.res_model, "sale.order")
        self.assertEqual(log.res_id, self.sale_order.id)
        self.assertEqual(log.partner_id.id, self.partner.id)
        self.assertEqual(log.status, "received")
        self.assertEqual(log.message_type, "button")
        self.assertTrue(self.sale_order._is_whatsapp_window_open(self.partner.phone))

    def test_14_incoming_button_reply_correlates_account_move_and_reactivates_window(
        self,
    ):
        """Verifica que al recibir un webhook con type='button' asociado a una factura (account.move):
        1. Se correlacione exactamente a la factura.
        2. Se reactive la ventana de atención de 24 horas de la factura.
        """
        journal = self.env["account.journal"].search(
            [("company_id", "=", self.company.id), ("type", "=", "sale")], limit=1,
        )
        if not journal:
            journal = self.env["account.journal"].create(
                {
                    "name": "Customer Invoices Test",
                    "type": "sale",
                    "code": "INVTEST",
                    "company_id": self.company.id,
                },
            )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "journal_id": journal.id,
                "invoice_date": fields.Date.today(),
            },
        )
        outbound_wamid = "wamid.HBgL_INV_OUTBOUND_BTN_02"
        self.env["whatsapp.message"].create(
            {
                "wamid": outbound_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "account.move",
                "res_id": invoice.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": fields.Datetime.now() - timedelta(hours=28),
            },
        )
        self.assertFalse(invoice._is_whatsapp_window_open(self.partner.phone))

        incoming_wamid = "wamid.HBgL_INV_BTN_REPLY_INBOUND_02"
        btn_text = "Confirmar Pago Factura"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "timestamp": str(
                                            int(fields.Datetime.now().timestamp()),
                                        ),
                                        "type": "button",
                                        "button": {
                                            "text": btn_text,
                                            "payload": "PAY_INV_CONFIRM",
                                        },
                                        "context": {"id": outbound_wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        self.assertTrue(invoice.message_ids)
        self.assertIn(btn_text, invoice.message_ids[0].body)
        log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertEqual(log.res_model, "account.move")
        self.assertEqual(log.res_id, invoice.id)
        self.assertTrue(invoice._is_whatsapp_window_open(self.partner.phone))

    def test_15_incoming_interactive_button_reply_reactivates_window(self):
        """Verifica que mensajes entrantes de tipo 'interactive' (button_reply):
        1. Se extraiga el title del botón.
        2. Se publique en Chatter y se registre con message_type='interactive'.
        3. Se reactive la ventana de 24 horas.
        """
        outbound_wamid = "wamid.HBgL_SO_OUTBOUND_INTERACTIVE_03"
        self.env["whatsapp.message"].create(
            {
                "wamid": outbound_wamid,
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "+16505559876",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "delivered",
                "date": fields.Datetime.now() - timedelta(hours=36),
            },
        )
        incoming_wamid = "wamid.HBgL_INTERACTIVE_REPLY_03"
        button_title = "Aprobar Presupuesto Ahora"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "timestamp": str(
                                            int(fields.Datetime.now().timestamp()),
                                        ),
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "btn_approve",
                                                "title": button_title,
                                            },
                                        },
                                        "context": {"id": outbound_wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        latest_msg = self.sale_order.message_ids[0]
        self.assertIn(button_title, latest_msg.body)
        log = self.env["whatsapp.message"].search(
            [("wamid", "=", incoming_wamid)], limit=1,
        )
        self.assertEqual(log.message_type, "interactive")
        self.assertTrue(self.sale_order._is_whatsapp_window_open(self.partner.phone))

    def test_16_incoming_button_reply_fallback_to_open_document_when_context_missing(
        self,
    ):
        """Verifica que si el botón llega sin context.id o con un WAMID no existente,
        se asocie al último documento abierto del contacto y reactive la ventana.
        """
        self.env["whatsapp.message"].search(
            [("partner_id", "=", self.partner.id)],
        ).unlink()
        self.assertFalse(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        incoming_wamid = "wamid.HBgL_UNQUOTED_BTN_04"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "timestamp": str(
                                            int(fields.Datetime.now().timestamp()),
                                        ),
                                        "type": "button",
                                        "button": {
                                            "text": "Consultar Estado",
                                            "payload": "CHECK_STATUS",
                                        },
                                        "context": {
                                            "id": "wamid.NON_EXISTENT_OUTBOUND_WAMID",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        self.assertIn("Consultar Estado", self.sale_order.message_ids[0].body)
        self.assertTrue(self.sale_order._is_whatsapp_window_open(self.partner.phone))

    def test_17_incoming_button_reply_idempotency_duplicate_delivery(self):
        """Verifica que entregas duplicadas del mismo evento de botón no dupliquen
        entradas en el Chatter ni registros en whatsapp.message.
        """
        incoming_wamid = "wamid.HBgL_DUP_BTN_05"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "button",
                                        "button": {"text": "Aceptar Términos"},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp1 = self.controller.webhook_receive()
            self.assertEqual(resp1.status_code, 200)

        initial_count = len(self.sale_order.message_ids)

        # Entrega duplicada
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp2 = self.controller.webhook_receive()
            self.assertEqual(resp2.status_code, 200)

        self.assertEqual(len(self.sale_order.message_ids), initial_count)
        self.assertEqual(
            self.env["whatsapp.message"].search_count([("wamid", "=", incoming_wamid)]),
            1,
        )

    def test_18_button_reply_window_reactivation_unblocks_freeform_composer(self):
        """Verifica que tras recibir la respuesta de un botón, el wizard de WhatsApp
        permita redactar en modo libre (freeform) sin rechazar por ventana cerrada.
        """
        self.env["whatsapp.message"].search(
            [("partner_id", "=", self.partner.id)],
        ).unlink()
        self.assertFalse(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        action = self.sale_order.action_send_whatsapp()
        self.assertFalse(action["context"]["default_is_window_open"])
        self.assertEqual(action["context"]["default_message_mode"], "template")

        incoming_wamid = "wamid.HBgL_REOPEN_BTN_06"
        payload = {
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559876",
                                        "profile": {"name": "Cliente WhatsApp"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559876",
                                        "id": incoming_wamid,
                                        "type": "button",
                                        "button": {"text": "Me interesa su oferta"},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = self._sign_payload(raw_body)
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": sig}, data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        self.assertTrue(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        action_reactivated = self.sale_order.action_send_whatsapp()
        self.assertTrue(action_reactivated["context"]["default_is_window_open"])
        self.assertEqual(
            action_reactivated["context"]["default_message_mode"], "freeform",
        )
