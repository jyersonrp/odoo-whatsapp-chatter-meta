# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class WhatsAppMessage(models.Model):
    _name = 'whatsapp.message'
    _description = 'Bitácora de Mensajes de WhatsApp (Meta Cloud API)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Referencia', compute='_compute_name', store=True)
    wamid = fields.Char(
        string='WhatsApp Message ID (wamid)',
        required=True,
        index=True,
        copy=False,
        help='Identificador único del mensaje emitido o recibido por Meta',
    )
    account_id = fields.Many2one(
        'whatsapp.account',
        string='Cuenta de WhatsApp',
        ondelete='set null',
    )
    company_id = fields.Many2one(
        'res.company',
        related='account_id.company_id',
        string='Compañía',
        store=True,
        readonly=True,
    )
    date = fields.Datetime(
        string='Fecha y Hora',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    sender = fields.Char(string='Remitente', required=True, index=True)
    recipient = fields.Char(string='Destinatario', required=True, index=True)
    direction = fields.Selection(
        selection=[
            ('outbound', 'Saliente'),
            ('inbound', 'Entrante'),
        ],
        string='Dirección',
        required=True,
        index=True,
    )
    message_type = fields.Selection(
        selection=[
            ('text', 'Texto'),
            ('template', 'Plantilla HSM'),
            ('document', 'Documento'),
            ('image', 'Imagen'),
            ('audio', 'Audio'),
            ('video', 'Video'),
            ('interactive', 'Interactivo'),
            ('other', 'Otro'),
        ],
        string='Tipo de Mensaje',
        default='text',
    )
    body = fields.Text(string='Contenido')
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Archivo Adjunto',
        ondelete='set null',
    )
    media_id = fields.Char(string='Meta Media ID')
    res_model = fields.Char(string='Modelo Vinculado', index=True)
    res_id = fields.Integer(string='ID del Registro', index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Contacto Asociado',
        index=True,
        ondelete='set null',
    )
    status = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('sent', 'Enviado'),
            ('delivered', 'Entregado'),
            ('read', 'Leído'),
            ('failed', 'Fallido'),
            ('received', 'Recibido'),
        ],
        string='Estado de Entrega',
        default='draft',
        index=True,
    )
    error_code = fields.Char(string='Error Code', index=True, readonly=True)
    error_message = fields.Text(string='Detalle de Error')
    raw_payload = fields.Text(string='Payload Crudo JSON')

    @api.depends('wamid', 'direction')
    def _compute_name(self):
        for msg in self:
            prefix = "OUT" if msg.direction == 'outbound' else "IN"
            short_id = (msg.wamid or '')[-8:]
            msg.name = f"WA-{prefix}-{short_id}"
