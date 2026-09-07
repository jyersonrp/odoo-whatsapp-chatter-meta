# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, tagged
from odoo.addons.whatsapp_chatter_meta.controllers.webhook import WhatsAppWebhookController


@tagged('post_install', '-at_install')
class TestWhatsAppWebhook(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = WhatsAppWebhookController()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente WhatsApp',
            'phone': '+16505559876',
        })
        cls.account = cls.env['whatsapp.account'].create({
            'name': 'Cuenta Webhook Test',
            'company_id': cls.company.id,
            'phone_number_id': '109999999999999',
            'waba_id': '209999999999999',
            'graph_api_token': 'EAAG_WEBHOOK_TOKEN',
            'webhook_verify_token': 'test_verify_token_123',
            'app_secret': 'super_secret_meta_app_secret_abc',
        })
        cls.sale_order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'state': 'draft',
        })

    def _sign_payload(self, payload_bytes, secret=None):
        secret = secret or self.account.app_secret
        sig_hash = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
        return f"sha256={sig_hash}"

    def _mock_request(self, args=None, headers=None, data=b''):
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
        mock_request = self._mock_request(args={
            'hub.mode': 'subscribe',
            'hub.verify_token': 'test_verify_token_123',
            'hub.challenge': 'CHALLENGE_STRING_789456',
        })
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_request):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.response[0].decode('utf-8'), 'CHALLENGE_STRING_789456')

    def test_02_get_handshake_invalid_token(self):
        """Verifica que un token de verificación incorrecto sea rechazado con HTTP 403."""
        mock_request = self._mock_request(args={
            'hub.mode': 'subscribe',
            'hub.verify_token': 'token_incorrecto',
            'hub.challenge': 'CHALLENGE_STRING_789456',
        })
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_request):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 403)

    def test_03_get_handshake_invalid_mode(self):
        """Verifica que un modo distinto a 'subscribe' sea rechazado con HTTP 403."""
        mock_request = self._mock_request(args={
            'hub.mode': 'unsubscribe',
            'hub.verify_token': 'test_verify_token_123',
            'hub.challenge': 'CHALLENGE_STRING_789456',
        })
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_request):
            resp = self.controller.webhook_verify()
            self.assertEqual(resp.status_code, 403)

    # -------------------------------------------------------------
    # POST HMAC-SHA256 Signature Verification Tests
    # -------------------------------------------------------------
    def test_04_post_signature_validation(self):
        """Verifica la validación criptográfica de la firma HMAC-SHA256 del Webhook."""
        payload_data = {'entry': []}
        raw_body = json.dumps(payload_data).encode('utf-8')
        valid_sig = self._sign_payload(raw_body)
        invalid_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        # Caso 1: Firma correcta -> 200
        mock_req_valid = self._mock_request(headers={'X-Hub-Signature-256': valid_sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req_valid):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Caso 2: Firma incorrecta -> 403
        mock_req_invalid = self._mock_request(headers={'X-Hub-Signature-256': invalid_sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req_invalid):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 403)

        # Caso 3: Sin firma en cabecera -> 403
        mock_req_nosig = self._mock_request(headers={}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req_nosig):
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
        outbound_wamid = 'wamid.HBgL_ORIGINAL_OUTBOUND_1001'
        self.env['whatsapp.message'].create({
            'wamid': outbound_wamid,
            'account_id': self.account.id,
            'sender': self.account.phone_number_id,
            'recipient': '+16505559876',
            'direction': 'outbound',
            'res_model': 'sale.order',
            'res_id': self.sale_order.id,
            'partner_id': self.partner.id,
            'status': 'delivered',
        })

        incoming_wamid = 'wamid.HBgL_REPLY_INBOUND_2002'
        incoming_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'contacts': [{'wa_id': '16505559876', 'profile': {'name': 'Cliente WhatsApp'}}],
                                'messages': [
                                    {
                                        'from': '16505559876',
                                        'id': incoming_wamid,
                                        'type': 'text',
                                        'text': {'body': 'Acepto la cotización, procedan.'},
                                        'context': {'id': outbound_wamid},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Verificar que se publicó en el Chatter de self.sale_order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        latest_msg = self.sale_order.message_ids[0]
        self.assertIn('Acepto la cotización, procedan', latest_msg.body)
        self.assertIn(incoming_wamid, latest_msg.body)

        # Verificar registro en bitácora whatsapp.message
        inbound_log = self.env['whatsapp.message'].search([('wamid', '=', incoming_wamid)], limit=1)
        self.assertTrue(inbound_log)
        self.assertEqual(inbound_log.direction, 'inbound')
        self.assertEqual(inbound_log.res_model, 'sale.order')
        self.assertEqual(inbound_log.res_id, self.sale_order.id)

    def test_06_incoming_unquoted_message_correlates_latest_open_document(self):
        """
        Verifica que un mensaje nuevo sin contexto se asocie al último documento abierto
        del contacto y se inserte en su Chatter.
        """
        incoming_wamid = 'wamid.HBgL_UNQUOTED_INBOUND_3003'
        incoming_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'contacts': [{'wa_id': '16505559876', 'profile': {'name': 'Cliente WhatsApp'}}],
                                'messages': [
                                    {
                                        'from': '16505559876',
                                        'id': incoming_wamid,
                                        'type': 'text',
                                        'text': {'body': 'Hola, ¿cuándo me entregan el pedido?'},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Debe asociarse automáticamente al pedido abierto self.sale_order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        latest_msg = self.sale_order.message_ids[0]
        self.assertIn('¿cuándo me entregan el pedido?', latest_msg.body)

    # -------------------------------------------------------------
    # Delivery Status Updates Tests
    # -------------------------------------------------------------
    def test_07_status_failed_alerts_in_chatter(self):
        """
        Verifica que al recibir un evento status == 'failed', se actualice la bitácora
        y se publique una advertencia de rechazo en el Chatter.
        """
        tracked_wamid = 'wamid.HBgL_TRACKED_OUTBOUND_4004'
        wa_msg = self.env['whatsapp.message'].create({
            'wamid': tracked_wamid,
            'account_id': self.account.id,
            'sender': self.account.phone_number_id,
            'recipient': '+16505559876',
            'direction': 'outbound',
            'res_model': 'sale.order',
            'res_id': self.sale_order.id,
            'partner_id': self.partner.id,
            'status': 'sent',
        })

        status_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'statuses': [
                                    {
                                        'id': tracked_wamid,
                                        'status': 'failed',
                                        'timestamp': '1725559999',
                                        'recipient_id': '16505559876',
                                        'errors': [
                                            {
                                                'code': 131026,
                                                'title': 'Message Undeliverable',
                                                'message': 'Recipient phone number not on WhatsApp',
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(status_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # 1. Comprobar que el estado de whatsapp.message pasó a 'failed' y tiene error_code
        wa_msg.invalidate_recordset()
        self.assertEqual(wa_msg.status, 'failed')
        self.assertEqual(wa_msg.error_code, '131026')
        self.assertIn('131026', wa_msg.error_message)
        self.assertIn('Recipient phone number not on WhatsApp', wa_msg.error_message)

        # 2. Comprobar alerta publicada en el Chatter de sale.order
        self.assertEqual(len(self.sale_order.message_ids), initial_count + 1)
        alert_msg = self.sale_order.message_ids[0]
        self.assertIn('Fallo en la entrega del mensaje de WhatsApp', alert_msg.body)
        self.assertIn('131026', alert_msg.body)

    def test_08_status_delivered_updates_message_status(self):
        """Verifica que evento de estado delivered actualice whatsapp.message."""
        tracked_wamid = 'wamid.HBgL_TRACKED_OUTBOUND_5005'
        wa_msg = self.env['whatsapp.message'].create({
            'wamid': tracked_wamid,
            'account_id': self.account.id,
            'sender': self.account.phone_number_id,
            'recipient': '+16505559876',
            'direction': 'outbound',
            'res_model': 'sale.order',
            'res_id': self.sale_order.id,
            'partner_id': self.partner.id,
            'status': 'sent',
        })

        status_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'statuses': [
                                    {
                                        'id': tracked_wamid,
                                        'status': 'delivered',
                                        'timestamp': '1725559999',
                                        'recipient_id': '16505559876',
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(status_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        wa_msg.invalidate_recordset()
        self.assertEqual(wa_msg.status, 'delivered')

    def test_09_webhook_idempotency_duplicate_message(self):
        """Verifica que mensajes con el mismo wamid no se publiquen dos veces en Chatter ni en bitácora."""
        incoming_wamid = 'wamid.HBgL_DUPLICATE_IDEMPOTENCY_7007'
        incoming_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'contacts': [{'wa_id': '16505559876', 'profile': {'name': 'Cliente WhatsApp'}}],
                                'messages': [
                                    {
                                        'from': '16505559876',
                                        'id': incoming_wamid,
                                        'type': 'text',
                                        'text': {'body': 'Mensaje que se entrega dos veces por reintento de Meta'},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        initial_count = len(self.sale_order.message_ids)
        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
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
        logs = self.env['whatsapp.message'].search([('wamid', '=', incoming_wamid)])
        self.assertEqual(len(logs), 1)

    def test_10_webhook_unknown_message_type_handling(self):
        """Verifica que tipos de mensajes no contemplados (ej. sticker, reaction) se registren como 'other' sin error."""
        incoming_wamid = 'wamid.HBgL_UNKNOWN_TYPE_8008'
        incoming_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'contacts': [{'wa_id': '16505559876', 'profile': {'name': 'Cliente WhatsApp'}}],
                                'messages': [
                                    {
                                        'from': '16505559876',
                                        'id': incoming_wamid,
                                        'type': 'reaction',
                                        'reaction': {'message_id': 'wamid.xxx', 'emoji': '👍'},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        log = self.env['whatsapp.message'].search([('wamid', '=', incoming_wamid)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.message_type, 'other')

    def test_11_webhook_unquoted_without_open_document_falls_back_to_partner_chatter(self):
        """Verifica que si no hay orden ni factura abierta, el mensaje se inserte en el Chatter del contacto."""
        partner_no_doc = self.env['res.partner'].create({
            'name': 'Contacto Sin Documentos',
            'phone': '+1 (650) 999-0000',
        })
        incoming_wamid = 'wamid.HBgL_FALLBACK_PARTNER_9009'
        incoming_payload = {
            'entry': [
                {
                    'id': self.account.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': self.account.phone_number_id},
                                'contacts': [{'wa_id': '16509990000', 'profile': {'name': 'Contacto Sin Documentos'}}],
                                'messages': [
                                    {
                                        'from': '16509990000',
                                        'id': incoming_wamid,
                                        'type': 'text',
                                        'text': {'body': 'Hola, quiero información general.'},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        initial_partner_msgs = len(partner_no_doc.message_ids)
        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        self.assertEqual(len(partner_no_doc.message_ids), initial_partner_msgs + 1)
        self.assertIn('información general', partner_no_doc.message_ids[0].body)

    test_11_webhook_incoming_message_fallback_matching_phone = test_11_webhook_unquoted_without_open_document_falls_back_to_partner_chatter

    def test_12_webhook_multi_account_resolution_by_phone_number_id(self):
        """Verifica que si hay múltiples cuentas, el webhook asocie el mensaje al account_id correcto por phone_number_id."""
        account2 = self.env['whatsapp.account'].create({
            'name': 'Cuenta Secundaria',
            'company_id': self.company.id,
            'phone_number_id': '999888777666555',
            'waba_id': '209999999999999',
            'graph_api_token': 'EAAG_TOKEN_2',
            'webhook_verify_token': 'token_2',
            'app_secret': self.account.app_secret,  # Mismo app secret de la app de Meta
        })

        incoming_wamid = 'wamid.HBgL_MULTI_ACC_10010'
        incoming_payload = {
            'entry': [
                {
                    'id': account2.waba_id,
                    'changes': [
                        {
                            'value': {
                                'messaging_product': 'whatsapp',
                                'metadata': {'phone_number_id': account2.phone_number_id},
                                'contacts': [{'wa_id': '16505559876', 'profile': {'name': 'Cliente WhatsApp'}}],
                                'messages': [
                                    {
                                        'from': '16505559876',
                                        'id': incoming_wamid,
                                        'type': 'text',
                                        'text': {'body': 'Mensaje dirigido al número secundario'},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }
        raw_body = json.dumps(incoming_payload).encode('utf-8')
        sig = self._sign_payload(raw_body)

        mock_req = self._mock_request(headers={'X-Hub-Signature-256': sig}, data=raw_body)
        with patch('odoo.addons.whatsapp_chatter_meta.controllers.webhook.request', new=mock_req):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        log = self.env['whatsapp.message'].search([('wamid', '=', incoming_wamid)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.account_id.id, account2.id)

