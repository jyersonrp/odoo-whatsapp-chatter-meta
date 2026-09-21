# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppTemplate(models.Model):
    _name = "whatsapp.template"
    _description = "Official Meta WhatsApp Template (HSM)"
    _check_company_auto = True

    name = fields.Char(
        string="Template Name in Meta",
        required=True,
        help="Exact template name approved in Meta Business Manager (lowercase letters and underscores)",
    )
    account_id = fields.Many2one(
        "whatsapp.account",
        string="WhatsApp Account",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="account_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Applicable Model",
        required=True,
        ondelete="cascade",
        help="Odoo model this template applies to (e.g. sale.order, account.move)",
    )
    model = fields.Char(
        string="Technical Model Name",
        related="model_id.model",
        store=True,
        readonly=True,
    )
    language = fields.Char(
        string="Language Code",
        required=True,
        default="es",
        help="ISO language code configured in Meta (e.g. es, en_US)",
    )
    header_type = fields.Selection(
        selection=[
            ("none", "No Header"),
            ("document", "PDF Document"),
            ("text", "Text"),
            ("image", "Image"),
        ],
        string="Header Type",
        default="none",
        required=True,
    )
    body = fields.Text(
        string="Message Body (with {{1}}, {{2}} placeholders)",
        required=True,
        help="Template content with numbered placeholders. Example: Hello {{1}}, we attach your quotation {{2}} for a total of {{3}}.",
    )
    variable_mapping = fields.Char(
        string="Dynamic Variable Mapping",
        help="Comma-separated list of model field paths to replace {{1}}, {{2}}, etc. "
        "Example: partner_id.name, name, amount_total",
    )
    escalation_hours = fields.Integer(
        string="Escalation Threshold (hours)",
        default=0,
        help="0 = use company default threshold",
    )
    escalation_threshold_hours = fields.Integer(
        related="escalation_hours",
        readonly=False,
        string="Escalation Threshold in Hours",
    )
    button_ids = fields.One2many(
        "whatsapp.template.button",
        "template_id",
        string="Buttons",
        copy=True,
    )
    button_count = fields.Integer(
        string="Button Count",
        compute="_compute_button_count",
    )
    active = fields.Boolean(string="Active", default=True)

    @api.depends("button_ids")
    def _compute_button_count(self):
        for template in self:
            template.button_count = len(template.button_ids)

    @api.constrains("escalation_hours")
    def _check_escalation_hours(self):
        for template in self:
            if template.escalation_hours and template.escalation_hours < 0:
                raise ValidationError(
                    _(
                        "Template escalation threshold cannot be negative.",
                    ),
                )

    def _get_effective_escalation_hours(self, company=None):
        self.ensure_one()
        if self.escalation_hours and self.escalation_hours > 0:
            return self.escalation_hours
        comp = company or self.company_id or self.env.company
        return getattr(comp, "whatsapp_escalation_hours", 72) or 72

    def _eval_button_dynamic_url(self, button, record):
        """Return full rendered URL for a dynamic button."""
        self.ensure_one()
        url = button.url or ""
        field_name = button.url_field_path or button.url_suffix_field or "name"
        val = str(self._eval_field_path(record, field_name) if record else "")
        if "{{1}}" in url:
            return url.replace("{{1}}", val)
        if re.search(r"\{\{[^}]+\}\}", url):
            return re.sub(r"\{\{[^}]+\}\}", val, url)
        if url.endswith("/"):
            return f"{url}{val}"
        return f"{url}/{val}" if val else url

    def _eval_field_path(self, record, path):
        """Safely evaluate a field expression (e.g. partner_id.name)."""
        val = record
        for part in path.strip().split("."):
            if not val:
                return ""
            try:
                val = getattr(val, part, "")
            except (AttributeError, KeyError, TypeError, ValueError):
                return ""

        if isinstance(val, bool):
            return "" if not val else _("Yes")
        if isinstance(val, models.BaseModel):
            return val.display_name or ""
        if isinstance(val, float):
            currency = getattr(record, "currency_id", False)
            if currency:
                return f"{currency.symbol} {val:,.2f}"
            return f"{val:,.2f}"
        if isinstance(val, int):
            return str(val)
        if hasattr(val, "strftime"):
            return val.strftime("%d/%m/%Y")
        return str(val or "")

    def _get_template_parameters(self, record):
        """Get list of computed values for template variables."""
        self.ensure_one()
        if self.variable_mapping:
            paths = [p.strip() for p in self.variable_mapping.split(",") if p.strip()]
        else:
            matches = re.findall(r"\{\{(\d+)\}\}", self.body or "")
            if not matches:
                return []
            placeholder_count = max(int(m) for m in matches)
            if record._name == "sale.order" or record._name == "account.move":
                default_paths = ["partner_id.name", "name", "amount_total"]
            else:
                default_paths = ["name"]
            paths = default_paths[:placeholder_count]

        return [self._eval_field_path(record, p) for p in paths]

    def _render_template_body(self, record):
        """Render template body replacing placeholders {{1}}, {{2}}..."""
        self.ensure_one()
        rendered = self.body or ""
        params = self._get_template_parameters(record)
        for idx, val in enumerate(params, start=1):
            rendered = rendered.replace(f"{{{{{idx}}}}}", str(val))
        return rendered

    def _get_meta_components(self, record=None, media_id=None, filename=None):
        """Build component structure required by Meta WhatsApp API."""
        self.ensure_one()
        components = []

        # Header
        if self.header_type == "document" and media_id:
            components.append(
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {
                                "id": media_id,
                                "filename": filename or "document.pdf",
                            },
                        },
                    ],
                },
            )

        # Body
        if record:
            params = self._get_template_parameters(record)
            if params:
                body_parameters = [{"type": "text", "text": str(p)} for p in params]
                components.append(
                    {
                        "type": "body",
                        "parameters": body_parameters,
                    },
                )

        # Interactive buttons (Meta Cloud API v21.0+)
        for idx, button in enumerate(self.button_ids):
            if button.button_type == "quick_reply":
                components.append(
                    {
                        "type": "button",
                        "sub_type": "quick_reply",
                        "index": str(idx),
                        "parameters": [
                            {
                                "type": "payload",
                                "payload": button.quick_reply_payload or button.name,
                            },
                        ],
                    },
                )
            elif button.button_type == "url" and button.url_type == "dynamic":
                field_name = button.url_field_path or button.url_suffix_field or "name"
                val = str(
                    self._eval_field_path(record, field_name)
                    if record
                    else (getattr(record, "name", "") if record else ""),
                )
                components.append(
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": str(idx),
                        "parameters": [
                            {
                                "type": "text",
                                "text": val,
                            },
                        ],
                    },
                )

        return components
