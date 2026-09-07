# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch, MagicMock
import requests

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestWhatsAppAccount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.account = cls.env['whatsapp.account'].create({
            'name': 'Cuenta Test WhatsApp',
            'company_id': cls.company.id,
            'phone_number_id': '100000000000001',
            'waba_id': '200000000000002',
            'graph_api_token': 'EAAG_TEST_TOKEN_12345',
            'api_version': 'v20.0',
            'webhook_verify_token': 'secret_verify_token_xyz',
            'app_secret': 'super_secret_app_key_456',
        })
        cls.company.whatsapp_account_id = cls.account.id

    def test_01_account_creation_and_default(self):
        """Verifica la creación y resolución predeterminada de cuenta multi-compañía."""
        self.assertTrue(self.account.id)
        default_acc = self.env['whatsapp.account']._get_default_account(company=self.company)
        self.assertEqual(default_acc.id, self.account.id)

    @patch('requests.post')
    @patch('requests.get')
    def test_02_action_test_connection_success(self, mock_get, mock_post):
        """Verifica que probar conexión exitosa retorna notificación client action."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'verified_name': 'Mi Empresa S.A.',
            'display_phone_number': '+52 55 1234 5678',
            'id': '100000000000001',
        }
        mock_get.return_value = mock_response

        res = self.account.action_test_connection()
        self.assertEqual(res['type'], 'ir.actions.client')
        self.assertEqual(res['tag'], 'display_notification')
        self.assertEqual(res['params']['type'], 'success')
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_03_action_test_connection_failure(self, mock_get):
        """Verifica que probar conexión fallida lanza UserError con detalles de Meta."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            'error': {
                'message': 'Invalid OAuth access token.',
                'type': 'OAuthException',
                'code': 190,
            }
        }
        mock_get.return_value = mock_response

        with self.assertRaises(UserError) as cm:
            self.account.action_test_connection()
        self.assertIn('190', str(cm.exception))
        self.assertIn('Invalid OAuth access token', str(cm.exception))

    @patch('requests.get', side_effect=requests.RequestException("Timeout de red"))
    def test_04_action_test_connection_network_error(self, mock_get):
        """Verifica manejo de errores de conectividad de red."""
        with self.assertRaises(UserError) as cm:
            self.account.action_test_connection()
        self.assertIn('Timeout de red', str(cm.exception))

    @patch('requests.post')
    def test_05_upload_media_success(self, mock_post):
        """Verifica subida directa en memoria de archivo binario a Meta /media."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 'media_meta_id_9999'}
        mock_post.return_value = mock_response

        dummy_pdf = b'%PDF-1.4 test binary content in memory'
        media_id = self.account.upload_media('Cotizacion_001.pdf', dummy_pdf, mimetype='application/pdf')
        self.assertEqual(media_id, 'media_meta_id_9999')

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('100000000000001/media', args[0])
        self.assertIn('file', kwargs['files'])
        self.assertEqual(kwargs['data']['messaging_product'], 'whatsapp')

    @patch('requests.post')
    def test_06_upload_media_failure(self, mock_post):
        """Verifica que error al subir a Meta /media lance UserError descriptivo."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'error': {
                'message': 'File size exceeds limit',
                'type': 'OAuthException',
                'code': 100,
            }
        }
        mock_post.return_value = mock_response

        with self.assertRaises(UserError) as cm:
            self.account.upload_media('test.pdf', b'content')
        self.assertIn('File size exceeds limit', str(cm.exception))

    @patch('requests.post')
    def test_07_dispatch_whatsapp_message_success(self, mock_post):
        """Verifica despacho de mensaje a Meta API /messages y extracción de wamid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'messaging_product': 'whatsapp',
            'contacts': [{'input': '5215512345678', 'wa_id': '5215512345678'}],
            'messages': [{'id': 'wamid.HBgLTEST123456789'}],
        }
        mock_post.return_value = mock_response

        payload = {
            'messaging_product': 'whatsapp',
            'to': '5215512345678',
            'type': 'text',
            'text': {'body': 'Hola prueba'},
        }
        wamid = self.account.dispatch_whatsapp_message(payload)
        self.assertEqual(wamid, 'wamid.HBgLTEST123456789')

    def test_08_res_config_settings_integration(self):
        """Verifica que Ajustes enlace correctamente con la cuenta de WhatsApp."""
        settings = self.env['res.config.settings'].create({
            'whatsapp_account_id': self.account.id,
        })
        self.assertEqual(settings.whatsapp_phone_number_id, '100000000000001')
        self.assertEqual(settings.whatsapp_waba_id, '200000000000002')
