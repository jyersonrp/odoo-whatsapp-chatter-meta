# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import logging
from markupsafe import escape as html_escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppComposerWizard(models.TransientModel):
    _name = 'whatsapp.composer.wizard'
    _description = 'Asistente de Envío de WhatsApp (Meta Cloud API)'

    res_model = fields.Char(string='Modelo del Documento', required=True)
    res_id = fields.Integer(string='ID del Documento', required=True)
    account_id = fields.Many2one(
        'whatsapp.account',
        string='Cuenta de WhatsApp',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='account_id.company_id',
        string='Compañía',
        readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Destinatario',
        required=True,
    )
    phone = fields.Char(
        string='Teléfono (E.164)',
        required=True,
        help='Número de teléfono del destinatario en formato internacional E.164 (ej. +5215512345678)',
    )
    is_window_open = fields.Boolean(
        string='Ventana de 24h Activa',
        default=False,
        readonly=True,
        help='Indica si el cliente ha interactuado en las últimas 24 horas permitiendo mensajes libres.',
    )
    message_mode = fields.Selection(
        selection=[
            ('template', 'Plantilla Oficial Meta (HSM)'),
            ('freeform', 'Mensaje Libre (Ventana 24h)'),
        ],
        string='Modo de Envío',
        default='template',
        required=True,
    )
    template_id = fields.Many2one(
        'whatsapp.template',
        string='Plantilla de WhatsApp',
        domain="[('account_id', '=', account_id), ('model', '=', res_model)]",
    )
    body = fields.Text(
        string='Mensaje / Previsualización',
        help='Contenido del mensaje a enviar o vista previa con las variables dinámicas sustituidas.',
    )
    attach_pdf = fields.Boolean(
        string='Adjuntar PDF Oficial',
        default=True,
        help='Compila en memoria el reporte oficial del documento y lo envía como adjunto a WhatsApp.',
    )
    report_action_id = fields.Many2one(
        'ir.actions.report',
        string='Reporte PDF',
    )
    pdf_filename = fields.Char(
        string='Nombre del Archivo PDF',
        default='documento.pdf',
    )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            raw_phone = getattr(self.partner_id, 'phone', False)
            if not raw_phone and 'mobile' in self.partner_id._fields:
                raw_phone = getattr(self.partner_id, 'mobile', False)
            raw_phone = raw_phone or ''
            self.phone = self.env['mail.thread']._format_whatsapp_phone(raw_phone, self.partner_id)

    @api.onchange('phone', 'partner_id')
    def _onchange_phone_partner(self):
        if self.phone and self.res_model and self.res_id:
            record = self.env[self.res_model].browse(self.res_id)
            if record.exists():
                self.is_window_open = record._is_whatsapp_window_open(phone=self.phone)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            if self.template_id.header_type == 'document':
                self.attach_pdf = True
            if self.res_model and self.res_id:
                record = self.env[self.res_model].browse(self.res_id)
                if record.exists():
                    self.body = self.template_id._render_template_body(record)

    @api.onchange('message_mode')
    def _onchange_message_mode(self):
        if self.message_mode == 'freeform' and not self.is_window_open:
            self.message_mode = 'template'
            return {
                'warning': {
                    'title': _("Ventana de 24 Horas Cerrada"),
                    'message': _(
                        "No es posible enviar un mensaje libre porque la ventana de atención al cliente de 24 horas "
                        "está inactiva. Meta exige el uso de una Plantilla Oficial aprobada (HSM)."
                    ),
                }
            }

    def action_send_whatsapp(self):
        self.ensure_one()
        # 1. Validar teléfono en estándar E.164
        formatted_phone = self.env['mail.thread']._format_whatsapp_phone(self.phone, self.partner_id)
        if not formatted_phone or len(formatted_phone) < 7:
            raise UserError(_("El número de teléfono proporcionado (%s) no es válido para WhatsApp.", self.phone))

        recipient_digits = formatted_phone.lstrip('+')

        # 2. Validar modo de mensaje contra ventana de 24 horas
        if self.message_mode == 'freeform' and not self.is_window_open:
            raise UserError(_(
                "La ventana de servicio de 24 horas no está activa. "
                "Debe seleccionar una Plantilla Oficial de Meta (HSM) para iniciar la conversación."
            ))

        if self.message_mode == 'template' and self.attach_pdf:
            if not self.is_window_open and self.template_id.header_type != 'document':
                raise UserError(_(
                    "Para adjuntar un PDF fuera de la ventana de 24 horas, la plantilla oficial seleccionada debe tener "
                    "una cabecera configurada de tipo Documento (PDF). Meta no permite mensajes multimedia independientes "
                    "fuera de la ventana de atención al cliente."
                ))

        # 3. Obtener registro objetivo
        if not self.res_model or self.res_model not in self.env:
            raise UserError(_("El modelo del documento (%s) no es válido.", self.res_model))
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_("El registro asociado no existe."))

        # 4. Generación de PDF en memoria si está habilitado
        pdf_content = None
        media_id = None
        filename = self.pdf_filename or "documento.pdf"
        if not filename.endswith('.pdf'):
            filename = f"{filename}.pdf"

        if self.attach_pdf:
            report = self.report_action_id
            if not report:
                if self.res_model == 'sale.order':
                    report = self.env.ref('sale.action_report_saleorder', raise_if_not_found=False)
                elif self.res_model == 'account.move':
                    report = self.env.ref('account.account_invoices', raise_if_not_found=False) or \
                             self.env.ref('account.account_invoices_without_payment', raise_if_not_found=False)

            if not report:
                raise UserError(_("No se encontró una acción de reporte configurada para compilar el PDF."))

            # Compilar PDF en memoria sin guardar archivos temporales en disco
            pdf_content, _report_ext = self.env['ir.actions.report'].with_context(report_pdf_no_attachment=True)._render_qweb_pdf(
                report.id, [record.id]
            )
            if not pdf_content:
                raise UserError(_("Ocurrió un error al compilar el reporte PDF en memoria."))

            if isinstance(pdf_content, str):
                pdf_content = pdf_content.encode('utf-8')

            # Subida directa como multipart/form-data a Meta API (/media)
            media_id = self.account_id.upload_media(filename, pdf_content, mimetype='application/pdf')

        # 5. Despacho a Meta WhatsApp Cloud API
        wamid = False
        secondary_wamid = False
        if self.message_mode == 'template':
            template = self.template_id
            if not template:
                raise UserError(_("Debe seleccionar una plantilla oficial para continuar."))

            # Si la plantilla tiene cabecera de tipo documento y tenemos media_id
            if template.header_type == 'document' and media_id:
                components = template._get_meta_components(record, media_id=media_id, filename=filename)
                payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'template',
                    'template': {
                        'name': template.name,
                        'language': {'code': template.language},
                        'components': components,
                    },
                }
                wamid = self.account_id.dispatch_whatsapp_message(payload)
            elif self.attach_pdf and media_id:
                # Si la plantilla no tiene cabecera de documento pero ventana 24h está activa:
                # 1. Despachar plantilla HSM
                components = template._get_meta_components(record)
                tpl_payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'template',
                    'template': {
                        'name': template.name,
                        'language': {'code': template.language},
                        'components': components,
                    },
                }
                wamid = self.account_id.dispatch_whatsapp_message(tpl_payload)

                # 2. Despachar mensaje de documento con media_id
                doc_payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'document',
                    'document': {
                        'id': media_id,
                        'filename': filename,
                    },
                }
                secondary_wamid = self.account_id.dispatch_whatsapp_message(doc_payload)
            else:
                components = template._get_meta_components(record)
                tpl_payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'template',
                    'template': {
                        'name': template.name,
                        'language': {'code': template.language},
                        'components': components,
                    },
                }
                wamid = self.account_id.dispatch_whatsapp_message(tpl_payload)

        else:  # Modo libre (freeform)
            if self.attach_pdf and media_id:
                doc_payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'document',
                    'document': {
                        'id': media_id,
                        'filename': filename,
                        'caption': self.body or '',
                    },
                }
                wamid = self.account_id.dispatch_whatsapp_message(doc_payload)
            else:
                text_payload = {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': recipient_digits,
                    'type': 'text',
                    'text': {
                        'body': self.body or '',
                    },
                }
                wamid = self.account_id.dispatch_whatsapp_message(text_payload)

        # 6. Crear adjunto para el Chatter si hubo PDF
        attachment = False
        if pdf_content:
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'raw': pdf_content,
                'res_model': record._name,
                'res_id': record.id,
                'mimetype': 'application/pdf',
            })

        # 7. Registrar mensaje saliente en el Chatter
        id_info = f"<code>{wamid}</code>"
        if secondary_wamid:
            id_info += f", Adjunto: <code>{secondary_wamid}</code>"
        chatter_body = (
            f"<p>📱 <strong>Mensaje enviado por WhatsApp ({formatted_phone}):</strong></p>"
            f"<p>{html_escape(self.body or '')}</p>"
            f"<p><small style='color: #6c757d;'>WhatsApp Message ID: {id_info}</small></p>"
        )
        record.message_post(
            body=chatter_body,
            attachment_ids=[attachment.id] if attachment else [],
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        # 8. Guardar auditoría en whatsapp.message
        self.env['whatsapp.message'].create({
            'wamid': wamid,
            'account_id': self.account_id.id,
            'sender': self.account_id.phone_number_id,
            'recipient': formatted_phone,
            'direction': 'outbound',
            'message_type': 'document' if (self.attach_pdf and not secondary_wamid) else ('template' if self.message_mode == 'template' else 'text'),
            'body': self.body or '',
            'attachment_id': attachment.id if (attachment and not secondary_wamid) else False,
            'media_id': media_id if not secondary_wamid else False,
            'res_model': record._name,
            'res_id': record.id,
            'partner_id': self.partner_id.id,
            'status': 'sent',
        })

        if secondary_wamid:
            self.env['whatsapp.message'].create({
                'wamid': secondary_wamid,
                'account_id': self.account_id.id,
                'sender': self.account_id.phone_number_id,
                'recipient': formatted_phone,
                'direction': 'outbound',
                'message_type': 'document',
                'body': filename,
                'attachment_id': attachment.id if attachment else False,
                'media_id': media_id or False,
                'res_model': record._name,
                'res_id': record.id,
                'partner_id': self.partner_id.id,
                'status': 'sent',
            })

        # 9. Notificación de éxito al usuario
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp Despachado"),
                'message': _("El mensaje y los adjuntos fueron enviados exitosamente a %s.", formatted_phone),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
