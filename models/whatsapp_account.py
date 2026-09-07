# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import secrets
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppAccount(models.Model):
    _name = 'whatsapp.account'
    _description = 'WhatsApp Business Account (Meta Cloud API)'
    _check_company_auto = True

    name = fields.Char(string='Nombre de la Cuenta', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    phone_number_id = fields.Char(
        string='Phone Number ID',
        required=True,
        help='ID del número de teléfono provisto por Meta WhatsApp Cloud API',
    )
    waba_id = fields.Char(
        string='WABA ID',
        required=True,
        help='WhatsApp Business Account ID',
    )
    graph_api_token = fields.Char(
        string='Access Token (Bearer)',
        required=True,
        help='Token de acceso permanente o de sistema generado en Meta Business Manager',
    )
    api_version = fields.Char(
        string='Versión de Graph API',
        required=True,
        default='v20.0',
        help='Versión de Meta Graph API (ej. v20.0)',
    )
    webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        required=True,
        default=lambda self: secrets.token_hex(16),
        help='Token de verificación utilizado en el handshake GET de Meta Webhook',
    )
    app_secret = fields.Char(
        string='App Secret',
        required=True,
        help='Secreto de la aplicación Meta para validar la firma HMAC-SHA256 de webhooks',
    )
    active = fields.Boolean(string='Activo', default=True)

    def _get_api_url(self, endpoint=''):
        self.ensure_one()
        version = self.api_version or 'v20.0'
        clean_endpoint = endpoint.lstrip('/')
        return f"https://graph.facebook.com/{version}/{clean_endpoint}"

    def _get_headers(self, is_json=True):
        self.ensure_one()
        headers = {
            'Authorization': f"Bearer {self.graph_api_token}",
        }
        if is_json:
            headers['Content-Type'] = 'application/json'
        return headers

    def action_test_connection(self):
        self.ensure_one()
        if not self.phone_number_id or not self.graph_api_token:
            raise UserError(_("Debe configurar el Phone Number ID y el Token de Acceso."))

        url = self._get_api_url(self.phone_number_id)
        headers = {
            'Authorization': f"Bearer {self.graph_api_token}",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
        except requests.RequestException as e:
            _logger.error("Error al conectar con Meta Graph API: %s", e)
            raise UserError(_("No se pudo establecer conexión con Meta Graph API: %s", str(e)))

        if response.status_code == 200:
            # Suscribir automáticamente la aplicación a los eventos del WABA
            if self.waba_id:
                try:
                    sub_url = self._get_api_url(f"{self.waba_id}/subscribed_apps")
                    requests.post(sub_url, headers=headers, timeout=5)
                except Exception as e:
                    _logger.warning("No se pudo suscribir la app al WABA automáticamente: %s", e)

            data = response.json()
            display_phone = data.get('display_phone_number', self.phone_number_id)
            verified_name = data.get('verified_name', 'Verificado')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Conexión Exitosa"),
                    'message': _("Conexión con Meta Cloud API validada correctamente. Teléfono: %s (%s)", display_phone, verified_name),
                    'type': 'success',
                    'sticky': False,
                },
            }
        else:
            try:
                err_data = response.json().get('error', {})
                err_msg = err_data.get('message', response.text)
                err_code = err_data.get('code', response.status_code)
            except Exception:
                err_msg = response.text
                err_code = response.status_code
            _logger.warning("Fallo al probar conexión de WhatsApp (%s): %s", err_code, err_msg)
            raise UserError(_("Fallo en la prueba de conexión con Meta (Código %s): %s", err_code, err_msg))

    @api.model
    def _get_default_account(self, company=None, raise_exception=False):
        company = company or self.env.company
        if company and company.whatsapp_account_id and company.whatsapp_account_id.active:
            return company.whatsapp_account_id
        account = self.search([('company_id', '=', company.id), ('active', '=', True)], order='id desc', limit=1)
        if not account and not raise_exception:
            # Fallback to any active account without company or any active account
            account = self.search([('active', '=', True)], order='id desc', limit=1)
        if not account and raise_exception:
            raise UserError(_("No hay una cuenta activa de WhatsApp configurada para la compañía %s.", company.name))
        return account

    def upload_media(self, filename, file_content, mimetype='application/pdf'):
        """
        Sube un binario directamente en memoria como multipart/form-data a Meta Cloud API.
        Endpoint: POST https://graph.facebook.com/{version}/{phone_number_id}/media
        """
        self.ensure_one()
        url = self._get_api_url(f"{self.phone_number_id}/media")
        headers = self._get_headers(is_json=False)
        files = {
            'file': (filename, file_content, mimetype),
        }
        data = {
            'messaging_product': 'whatsapp',
            'type': mimetype,
        }

        try:
            response = requests.post(url, headers=headers, data=data, files=files, timeout=30)
        except requests.RequestException as e:
            _logger.error("Error de red al subir archivo multimedia a WhatsApp: %s", e)
            raise UserError(_("Error de red al subir archivo a WhatsApp: %s", str(e)))

        if response.status_code == 200:
            res_data = response.json()
            media_id = res_data.get('id')
            if not media_id:
                raise UserError(_("Meta no devolvió un ID multimedia válido: %s", response.text))
            _logger.info("Archivo %s subido exitosamente a Meta con media_id: %s", filename, media_id)
            return media_id
        else:
            try:
                err_data = response.json().get('error', {})
                err_msg = err_data.get('message', response.text)
                err_code = err_data.get('code', response.status_code)
            except Exception:
                err_msg = response.text
                err_code = response.status_code
            _logger.error("Error de Meta al subir archivo multimedia (%s): %s", err_code, err_msg)
            raise UserError(_("Error de Meta al subir archivo (%s): %s", err_code, err_msg))

    def dispatch_whatsapp_message(self, payload):
        """
        Despacha un mensaje a Meta WhatsApp Cloud API.
        Endpoint: POST https://graph.facebook.com/{version}/{phone_number_id}/messages
        """
        self.ensure_one()
        url = self._get_api_url(f"{self.phone_number_id}/messages")
        headers = self._get_headers(is_json=True)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
        except requests.RequestException as e:
            _logger.error("Error de red al despachar mensaje WhatsApp: %s", e)
            raise UserError(_("Error de red al enviar mensaje de WhatsApp: %s", str(e)))

        if response.status_code in (200, 201):
            res_data = response.json()
            messages = res_data.get('messages', [])
            if messages and 'id' in messages[0]:
                return messages[0]['id']
            raise UserError(_("Respuesta inesperada de Meta al enviar mensaje: %s", response.text))
        else:
            try:
                err_data = response.json().get('error', {})
                err_msg = err_data.get('message', response.text)
                err_code = err_data.get('code', response.status_code)
            except Exception:
                err_msg = response.text
                err_code = response.status_code
            _logger.error("Error de Meta al enviar mensaje (%s): %s", err_code, err_msg)
            raise UserError(_("Error de Meta al enviar mensaje (%s): %s", err_code, err_msg))
