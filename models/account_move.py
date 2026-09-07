# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_send_whatsapp(self):
        self.ensure_one()
        partner = self.partner_id
        raw_phone = getattr(partner, 'phone', '') or (getattr(partner, 'mobile', '') if 'mobile' in partner._fields else '') or ''
        phone = self._format_whatsapp_phone(raw_phone, partner)
        account = self.env['whatsapp.account']._get_default_account(company=self.company_id)
        is_window_open = self._is_whatsapp_window_open(phone)

        report = self.env.ref('account.account_invoices', raise_if_not_found=False) or \
                 self.env.ref('account.account_invoices_without_payment', raise_if_not_found=False)

        inv_safe_name = (self.name or 'Factura').replace('/', '_').replace(' ', '_')
        friendly_filename = f"Factura_{inv_safe_name}.pdf"

        # Preload corresponding template and rendered text
        template = False
        if account:
            template = self.env['whatsapp.template'].search([
                ('account_id', '=', account.id),
                ('model', '=', self._name),
                ('active', '=', True),
            ], order='header_type desc, id desc', limit=1)
        if not template:
            template = self.env['whatsapp.template'].search([
                ('model', '=', self._name),
                ('active', '=', True),
            ], order='header_type desc, id desc', limit=1)

        default_body = ""
        if template:
            default_body = template._render_template_body(self)
        elif is_window_open:
            total_str = f"{self.currency_id.symbol} {self.amount_total:,.2f}" if self.currency_id else f"{self.amount_total:,.2f}"
            default_body = _("Hola %s, le compartimos la factura %s por un total de %s.") % (
                partner.name or '', self.name or '', total_str
            )

        return {
            'name': _('Enviar Factura por WhatsApp'),
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.composer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_partner_id': partner.id,
                'default_phone': phone,
                'default_account_id': account.id if account else False,
                'default_template_id': template.id if template else False,
                'default_body': default_body,
                'default_attach_pdf': True,
                'default_report_action_id': report.id if report else False,
                'default_pdf_filename': friendly_filename,
                'default_is_window_open': is_window_open,
                'default_message_mode': 'freeform' if is_window_open else 'template',
            },
        }
