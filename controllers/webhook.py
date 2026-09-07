# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hmac
import hashlib
import json
import logging
import re
from markupsafe import escape as html_escape

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class WhatsAppWebhookController(http.Controller):

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def webhook_verify(self, **kwargs):
        """
        Handshake de verificación de Meta Graph API (GET).
        Parámetros esperados: hub.mode, hub.verify_token, hub.challenge.
        """
        mode = request.httprequest.args.get('hub.mode') or kwargs.get('hub.mode')
        token = request.httprequest.args.get('hub.verify_token') or kwargs.get('hub.verify_token')
        challenge = request.httprequest.args.get('hub.challenge') or kwargs.get('hub.challenge')

        if mode == 'subscribe' and token and challenge:
            account = request.env['whatsapp.account'].sudo().search([
                ('webhook_verify_token', '=', token),
                ('active', '=', True),
            ], limit=1)

            if account:
                _logger.info("Handshake de WhatsApp exitoso para cuenta: %s", account.name)
                return Response(str(challenge), status=200, content_type='text/plain')

        _logger.warning("Handshake de WhatsApp fallido. mode: %s, token provisto: %s", mode, token)
        return Response("Forbidden", status=403, content_type='text/plain')

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def webhook_receive(self, **kwargs):
        """
        Receptor de eventos y mensajes de Meta WhatsApp Cloud API (POST).
        Valida la firma HMAC-SHA256 (X-Hub-Signature-256) contra el App Secret.
        """
        raw_body = request.httprequest.get_data()
        signature_header = request.httprequest.headers.get('X-Hub-Signature-256', '')

        if not signature_header or not raw_body:
            _logger.warning("Petición de Webhook de WhatsApp sin firma o cuerpo vacío.")
            return Response("Invalid signature", status=403, content_type='text/plain')

        # Buscar cuenta activa cuya clave App Secret valide la firma HMAC-SHA256
        active_accounts = request.env['whatsapp.account'].sudo().search([('active', '=', True)])
        matching_account = False

        for account in active_accounts:
            if not account.app_secret:
                continue
            expected_sig = "sha256=" + hmac.new(
                account.app_secret.encode('utf-8'),
                raw_body,
                hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(expected_sig, signature_header):
                matching_account = account
                break

        if not matching_account:
            _logger.warning("Firma HMAC-SHA256 de WhatsApp inválida o no coincide con ninguna cuenta activa.")
            return Response("Invalid signature", status=403, content_type='text/plain')

        # Procesar contenido JSON del webhook
        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            _logger.error("Error al decodificar JSON del webhook de WhatsApp: %s", e)
            return Response(json.dumps({'error': 'Invalid JSON'}), status=400, content_type='application/json')

        try:
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if not value:
                        continue

                    # Identificar cuenta exacta a partir de phone_number_id de metadatos si está disponible
                    phone_number_id = value.get('metadata', {}).get('phone_number_id')
                    account_for_change = matching_account
                    if phone_number_id:
                        exact_acc = request.env['whatsapp.account'].sudo().search([
                            ('phone_number_id', '=', str(phone_number_id)),
                            ('active', '=', True),
                        ], limit=1)
                        if exact_acc:
                            account_for_change = exact_acc

                    # Procesar mensajes entrantes
                    messages = value.get('messages', [])
                    if messages:
                        self._process_incoming_messages(value, account_for_change)

                    # Procesar eventos de estado (delivery statuses)
                    statuses = value.get('statuses', [])
                    if statuses:
                        self._process_status_updates(statuses, account_for_change)
        except Exception as e:
            _logger.exception("Error inesperado procesando webhook de WhatsApp: %s", e)

        return Response(json.dumps({'status': 'ok'}), status=200, content_type='application/json')

    def _process_incoming_messages(self, value, account):
        """Procesa mensajes recibidos y los correlaciona con Chatter con control de idempotencia."""
        messages = value.get('messages', [])
        contacts = {c.get('wa_id'): c.get('profile', {}).get('name') for c in value.get('contacts', [])}

        for msg in messages:
            from_phone = msg.get('from', '')
            wamid = msg.get('id', '')
            msg_type = msg.get('type', 'text')

            if not wamid:
                continue

            # Verificación de idempotencia: ignorar entregas duplicadas de Meta
            existing_msg = request.env['whatsapp.message'].sudo().search([
                ('wamid', '=', wamid),
            ], limit=1)
            if existing_msg:
                _logger.info("Mensaje de WhatsApp con wamid %s ya fue procesado previamente. Ignorando duplicado.", wamid)
                continue

            # Extraer contenido de texto
            body_text = ""
            if msg_type == 'text':
                body_text = msg.get('text', {}).get('body', '')
            elif msg_type == 'button':
                body_text = msg.get('button', {}).get('text', '')
            elif msg_type == 'interactive':
                body_text = (
                    msg.get('interactive', {}).get('button_reply', {}).get('title')
                    or msg.get('interactive', {}).get('list_reply', {}).get('title')
                    or ''
                )
            elif msg_type in ('image', 'document', 'audio', 'video'):
                caption = msg.get(msg_type, {}).get('caption', '')
                body_text = f"[{msg_type.upper()}] {caption}".strip()
            else:
                body_text = f"[{msg_type}]"

            # 1. Identificar contacto por número de teléfono
            partner = self._find_partner_by_phone(from_phone)

            # 2. Correlación de documento objetivo
            target_record = False
            context_id = msg.get('context', {}).get('id')

            # a) Correlación por mensaje previo citado (context.id)
            if context_id:
                prev_msg = request.env['whatsapp.message'].sudo().search([
                    ('wamid', '=', context_id),
                ], limit=1)
                if prev_msg and prev_msg.res_model and prev_msg.res_id:
                    if prev_msg.res_model in request.env:
                        rec = request.env[prev_msg.res_model].sudo().browse(prev_msg.res_id)
                        if rec.exists():
                            target_record = rec

            # b) Correlación por último documento abierto del contacto
            if not target_record and partner:
                target_record = self._find_latest_open_document(partner)

            # c) Fallback al registro del partner si no hay documento abierto
            if not target_record and partner:
                target_record = partner

            # 3. Publicar nota en el Chatter del documento objetivo
            if target_record:
                author_id = partner.id if partner else False
                author_name = contacts.get(from_phone) or partner.name if partner else from_phone
                chatter_body = (
                    f"<p>💬 <strong>Respuesta recibida por WhatsApp ({from_phone} - {author_name}):</strong></p>"
                    f"<p>{html_escape(body_text)}</p>"
                    f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{wamid}</code></small></p>"
                )
                target_record.message_post(
                    body=chatter_body,
                    author_id=author_id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

            valid_types = {'text', 'template', 'document', 'image', 'audio', 'video', 'interactive'}
            stored_type = msg_type if msg_type in valid_types else 'other'

            # 4. Registrar en bitácora whatsapp.message
            request.env['whatsapp.message'].sudo().create({
                'wamid': wamid,
                'account_id': account.id,
                'sender': from_phone,
                'recipient': account.phone_number_id,
                'direction': 'inbound',
                'message_type': stored_type,
                'body': body_text,
                'res_model': target_record._name if target_record else False,
                'res_id': target_record.id if target_record else False,
                'partner_id': partner.id if partner else False,
                'status': 'received',
                'raw_payload': json.dumps(msg),
            })

    def _find_partner_by_phone(self, phone):
        """Busca un partner por coincidencia de número telefónico normalizado."""
        if not phone:
            return request.env['res.partner']
        digits = re.sub(r'\D', '', str(phone))
        if not digits:
            return request.env['res.partner']

        e164_variant = f"+{digits}"
        partner_model = request.env['res.partner'].sudo()

        conditions = [('phone', '=', e164_variant)]
        if 'phone_sanitized' in partner_model._fields:
            conditions.append(('phone_sanitized', '=', e164_variant))
        if 'phone' in partner_model._fields:
            conditions.append(('phone', 'ilike', digits[-10:]))
        if 'phone_mobile_search' in partner_model._fields:
            conditions.append(('phone_mobile_search', 'ilike', digits[-10:]))
        if 'mobile' in partner_model._fields:
            conditions.append(('mobile', 'ilike', digits[-10:]))

        domain = []
        if len(conditions) > 1:
            domain = ['|'] * (len(conditions) - 1) + conditions
        elif conditions:
            domain = conditions

        return partner_model.search(domain, limit=1)

    def _find_latest_open_document(self, partner):
        """
        Encuentra el documento abierto más reciente (sale.order o account.move)
        perteneciente al contacto.
        """
        partner_domain = [('partner_id', 'child_of', partner.commercial_partner_id.id)]

        # sale.order en estado cotización o venta
        recent_sale = request.env['sale.order'].sudo().search(
            partner_domain + [('state', 'in', ('draft', 'sent', 'sale'))],
            order='write_date desc, id desc',
            limit=1
        )

        # account.move tipo factura de cliente publicada o borrador no pagada
        recent_invoice = request.env['account.move'].sudo().search(
            partner_domain + [
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', 'in', ('draft', 'posted')),
                ('payment_state', 'in', ('not_paid', 'partial', 'in_payment')),
            ],
            order='write_date desc, id desc',
            limit=1
        )

        if recent_sale and recent_invoice:
            sale_date = recent_sale.write_date or recent_sale.create_date
            inv_date = recent_invoice.write_date or recent_invoice.create_date
            return recent_sale if sale_date >= inv_date else recent_invoice
        elif recent_sale:
            return recent_sale
        elif recent_invoice:
            return recent_invoice

        return False

    def _process_status_updates(self, statuses, account):
        """Actualiza estados de entrega (sent, delivered, read, failed) y alerta si falló con control de duplicados."""
        for st in statuses:
            status_wamid = st.get('id', '')
            status_val = st.get('status', '')  # sent, delivered, read, failed

            msg_record = request.env['whatsapp.message'].sudo().search([
                ('wamid', '=', status_wamid),
            ], limit=1)

            if not msg_record:
                continue

            # Idempotencia: si ya tiene este mismo estado registrado, no repetir alertas ni escrituras
            if msg_record.status == status_val:
                continue

            vals = {'status': status_val}

            if status_val == 'failed':
                errors = st.get('errors', [])
                err_parts = []
                for err in errors:
                    code = err.get('code', 'N/A')
                    title = err.get('title', 'Error')
                    details = err.get('details') or err.get('message', '')
                    err_parts.append(f"[{code}] {title}: {details}")

                full_err = "; ".join(err_parts) or "Error de entrega desconocido reportado por Meta."
                vals['error_message'] = full_err
                if errors and errors[0].get('code') is not None:
                    vals['error_code'] = str(errors[0].get('code'))

                # Publicar alerta en el Chatter del documento original
                if msg_record.res_model and msg_record.res_id and msg_record.res_model in request.env:
                    doc = request.env[msg_record.res_model].sudo().browse(msg_record.res_id)
                    if doc.exists():
                        warning_body = (
                            f"<p>⚠️ <strong>Fallo en la entrega del mensaje de WhatsApp:</strong></p>"
                            f"<p>El mensaje enviado a <strong>{msg_record.recipient}</strong> no pudo ser entregado.</p>"
                            f"<p style='color: #dc3545;'><strong>Motivo:</strong> {html_escape(full_err)}</p>"
                            f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{status_wamid}</code></small></p>"
                        )
                        doc.message_post(
                            body=warning_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )

            msg_record.write(vals)
