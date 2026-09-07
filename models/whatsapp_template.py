# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class WhatsAppTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'Plantilla Oficial de Meta WhatsApp (HSM)'
    _check_company_auto = True

    name = fields.Char(
        string='Nombre de la Plantilla en Meta',
        required=True,
        help='Nombre exacto de la plantilla aprobada en el Business Manager de Meta (letras minúsculas y guiones bajos)',
    )
    account_id = fields.Many2one(
        'whatsapp.account',
        string='Cuenta de WhatsApp',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        related='account_id.company_id',
        string='Compañía',
        store=True,
        readonly=True,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Modelo Aplicable',
        required=True,
        ondelete='cascade',
        help='Modelo de Odoo al que aplica esta plantilla (ej. sale.order, account.move)',
    )
    model = fields.Char(
        string='Nombre Técnico del Modelo',
        related='model_id.model',
        store=True,
        readonly=True,
    )
    language = fields.Char(
        string='Código de Idioma',
        required=True,
        default='es',
        help='Código ISO del idioma configurado en Meta (ej. es, en_US)',
    )
    header_type = fields.Selection(
        selection=[
            ('none', 'Sin Cabecera'),
            ('document', 'Documento PDF'),
            ('text', 'Texto'),
            ('image', 'Imagen'),
        ],
        string='Tipo de Cabecera',
        default='none',
        required=True,
    )
    body = fields.Text(
        string='Cuerpo del Mensaje (con marcadores {{1}}, {{2}})',
        required=True,
        help='Contenido de la plantilla con marcadores numéricos. Ejemplo: Hola {{1}}, adjuntamos su cotización {{2}} por un total de {{3}}.',
    )
    variable_mapping = fields.Char(
        string='Mapeo Dinámico de Variables',
        help='Lista separada por comas de rutas de campos del modelo para sustituir {{1}}, {{2}}, etc. '
             'Ejemplo: partner_id.name, name, amount_total',
    )
    active = fields.Boolean(string='Activo', default=True)

    def _eval_field_path(self, record, path):
        """Evalúa de forma segura una expresión de campo (ej. partner_id.name)."""
        val = record
        for part in path.strip().split('.'):
            if not val:
                return ''
            try:
                val = getattr(val, part, '')
            except Exception:
                return ''

        if isinstance(val, bool):
            return '' if not val else 'Sí'
        if isinstance(val, models.BaseModel):
            return val.display_name or ''
        if isinstance(val, float):
            currency = getattr(record, 'currency_id', False)
            if currency:
                return f"{currency.symbol} {val:,.2f}"
            return f"{val:,.2f}"
        if isinstance(val, int):
            return str(val)
        if hasattr(val, 'strftime'):
            return val.strftime('%d/%m/%Y')
        return str(val or '')

    def _get_template_parameters(self, record):
        """Obtiene la lista de valores calculados para las variables de la plantilla."""
        self.ensure_one()
        import re
        if self.variable_mapping:
            paths = [p.strip() for p in self.variable_mapping.split(',') if p.strip()]
        else:
            matches = re.findall(r'\{\{(\d+)\}\}', self.body or '')
            if not matches:
                return []
            placeholder_count = max(int(m) for m in matches)
            if record._name == 'sale.order':
                default_paths = ['partner_id.name', 'name', 'amount_total']
            elif record._name == 'account.move':
                default_paths = ['partner_id.name', 'name', 'amount_total']
            else:
                default_paths = ['name']
            paths = default_paths[:placeholder_count]

        return [self._eval_field_path(record, p) for p in paths]

    def _render_template_body(self, record):
        """Renderiza el texto de la plantilla reemplazando los marcadores {{1}}, {{2}}..."""
        self.ensure_one()
        rendered = self.body or ''
        params = self._get_template_parameters(record)
        for idx, val in enumerate(params, start=1):
            rendered = rendered.replace(f"{{{{{idx}}}}}", str(val))
        return rendered

    def _get_meta_components(self, record, media_id=None, filename=None):
        """Construye la estructura de componentes requerida por Meta WhatsApp API."""
        self.ensure_one()
        components = []

        # Cabecera
        if self.header_type == 'document' and media_id:
            components.append({
                'type': 'header',
                'parameters': [
                    {
                        'type': 'document',
                        'document': {
                            'id': media_id,
                            'filename': filename or 'documento.pdf',
                        },
                    },
                ],
            })

        # Cuerpo
        params = self._get_template_parameters(record)
        if params:
            body_parameters = [{'type': 'text', 'text': str(p)} for p in params]
            components.append({
                'type': 'body',
                'parameters': body_parameters,
            })

        return components
