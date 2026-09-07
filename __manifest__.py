# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'WhatsApp Chatter Integration (Meta Cloud API)',
    'version': '19.0.1.0.0',
    'category': 'Sales/Marketing',
    'summary': 'Transactional WhatsApp Chatter Integration with Meta WhatsApp Cloud API',
    'description': """
Módulo de Integración de WhatsApp Transaccional en el Chatter (Odoo + Meta API)
=============================================================================
- Botón de acción en cabecera: "Enviar por WhatsApp" en sale.order y account.move que abre un Wizard con texto y plantilla precargada.
- Generación de PDF en memoria: Compila reporte de cotización/factura vía ir.actions.report._render_qweb_pdf y lo sube como binario a Meta Cloud API (/media).
- Despacho de mensajes tipo document con media_id y nombre amigable (Cotizacion_SO001.pdf / Factura_INV001.pdf).
- Webhook receptor (Controller http.route /whatsapp/webhook):
  * Handshake GET con validación de hub.verify_token.
  * Verificación criptográfica POST HMAC-SHA256 con App Secret (X-Hub-Signature-256).
  * Correlación con contexto (context.id / wamid) o búsqueda de último documento abierto del contacto.
  * Publicación automática de respuestas y eventos de entrega en el Chatter.
- Gestión multi-compañía de cuentas whatsapp.account integrada en Ajustes.
- Bitácora de auditoría whatsapp.message.
    """,
    'author': 'Yerson R.',
    'depends': [
        'base',
        'mail',
        'sale',
        'account',
        'phone_validation',
    ],
    'data': [
        'security/whatsapp_security.xml',
        'security/ir.model.access.csv',
        'views/whatsapp_account_views.xml',
        'views/whatsapp_template_views.xml',
        'views/whatsapp_message_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'wizard/whatsapp_composer_wizard_views.xml',
        'views/whatsapp_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
