# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    whatsapp_account_id = fields.Many2one(
        "whatsapp.account",
        string="Default WhatsApp Account",
        help="Meta Cloud API WhatsApp account configured for this company",
    )
    whatsapp_escalation_hours = fields.Integer(
        string="WhatsApp Escalation Threshold (hours)",
        default=72,
        help="Hours of inactivity or lack of response before escalating to call activity",
    )
    whatsapp_escalation_threshold_hours = fields.Integer(
        string="WhatsApp Escalation Threshold in Hours",
        related="whatsapp_escalation_hours",
        readonly=False,
    )
    whatsapp_invoice_logo = fields.Binary(
        string="WhatsApp Invoice Logo",
        attachment=True,
        help="Custom high-contrast logo used specifically for WhatsApp modern invoice PDF reports. Falls back to company logo if not set.",
    )

    def _get_whatsapp_invoice_logo(self):
        """Return the dedicated WhatsApp invoice logo if configured, otherwise company logo."""
        self.ensure_one()
        return self.whatsapp_invoice_logo or self.logo

    @api.constrains("whatsapp_escalation_hours", "whatsapp_escalation_threshold_hours")
    def _check_whatsapp_escalation_hours(self):
        for company in self:
            if company.whatsapp_escalation_hours <= 0:
                raise ValidationError(
                    _("The escalation threshold must be greater than 0 hours."),
                )
