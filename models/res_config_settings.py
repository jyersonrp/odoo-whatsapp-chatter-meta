# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    whatsapp_account_id = fields.Many2one(
        'whatsapp.account',
        related='company_id.whatsapp_account_id',
        readonly=False,
        string='Cuenta de WhatsApp',
    )
    whatsapp_phone_number_id = fields.Char(
        related='whatsapp_account_id.phone_number_id',
        readonly=False,
        string='Phone Number ID',
    )
    whatsapp_waba_id = fields.Char(
        related='whatsapp_account_id.waba_id',
        readonly=False,
        string='WABA ID',
    )
    whatsapp_graph_api_token = fields.Char(
        related='whatsapp_account_id.graph_api_token',
        readonly=False,
        string='Access Token (Bearer)',
    )
    whatsapp_webhook_verify_token = fields.Char(
        related='whatsapp_account_id.webhook_verify_token',
        readonly=False,
        string='Webhook Verify Token',
    )
    whatsapp_app_secret = fields.Char(
        related='whatsapp_account_id.app_secret',
        readonly=False,
        string='App Secret',
    )

    def action_test_whatsapp_connection(self):
        self.ensure_one()
        if not self.whatsapp_account_id:
            raise UserError(_("Debe seleccionar o configurar una cuenta de WhatsApp primero."))
        return self.whatsapp_account_id.action_test_connection()
