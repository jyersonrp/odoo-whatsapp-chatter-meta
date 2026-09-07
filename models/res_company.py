# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    whatsapp_account_id = fields.Many2one(
        'whatsapp.account',
        string='Cuenta de WhatsApp Predeterminada',
        help='Cuenta de WhatsApp Meta Cloud API configurada para esta compañía',
    )
