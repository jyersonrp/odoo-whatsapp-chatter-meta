from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WhatsAppTemplateButton(models.Model):
    _name = "whatsapp.template.button"
    _description = "Meta WhatsApp Template Button"
    _order = "sequence, id"
    _check_company_auto = True

    template_id = fields.Many2one(
        "whatsapp.template",
        string="Template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )
    company_id = fields.Many2one(
        "res.company",
        related="template_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    button_type = fields.Selection(
        selection=[
            ("phone_number", "Call Phone"),
            ("quick_reply", "Quick Reply"),
            ("url", "Visit Website"),
        ],
        string="Button Type",
        required=True,
        default="quick_reply",
    )
    name = fields.Char(
        string="Button Label",
        required=True,
        translate=False,
    )
    phone_number = fields.Char(
        string="Phone Number",
        help="Phone number with country code (e.g. +16505551234)",
    )
    url_type = fields.Selection(
        selection=[
            ("static", "Static"),
            ("dynamic", "Dynamic"),
        ],
        string="URL Type",
        default="static",
        required=True,
    )
    url = fields.Char(
        string="Website URL",
        help="Target URL. For dynamic URLs, may include {{1}} or {{field}} placeholder",
    )
    url_field_path = fields.Char(
        string="Dynamic Field (Optional)",
        default="name",
        help="Model field path to evaluate as suffix (e.g. name, access_token, id)",
    )
    url_suffix_field = fields.Char(
        string="URL Suffix (Alias)",
        compute="_compute_url_suffix_field",
        inverse="_inverse_url_suffix_field",
        store=True,
        help="Compatibility alias for url_field_path",
    )
    quick_reply_payload = fields.Char(
        string="Custom Payload",
        help="Payload for quick_reply in Meta Cloud API",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped("template_id").invalidate_recordset(["button_ids"])
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"template_id", "button_type", "sequence"} & set(vals.keys()):
            self.mapped("template_id").invalidate_recordset(["button_ids"])
        return res

    def unlink(self):
        templates = self.mapped("template_id")
        res = super().unlink()
        templates.invalidate_recordset(["button_ids"])
        return res

    @api.depends("url_field_path")
    def _compute_url_suffix_field(self):
        for button in self:
            button.url_suffix_field = button.url_field_path

    def _inverse_url_suffix_field(self):
        for button in self:
            if button.url_suffix_field:
                button.url_field_path = button.url_suffix_field

    @api.constrains("template_id", "button_type")
    def _check_button_limits(self):
        for template in self.mapped("template_id"):
            template.invalidate_recordset(["button_ids"])
            buttons = template.button_ids
            if len(buttons) > 10:
                raise ValidationError(
                    _(
                        "A WhatsApp template cannot have more than 10 buttons in total per Meta specifications.",
                    ),
                )

            phone_buttons = buttons.filtered(lambda b: b.button_type == "phone_number")
            if len(phone_buttons) > 1:
                raise ValidationError(
                    _(
                        "Only a maximum of 1 'Call Phone' (PHONE_NUMBER) button is allowed per template.",
                    ),
                )

            url_buttons = buttons.filtered(lambda b: b.button_type == "url")
            if len(url_buttons) > 2:
                raise ValidationError(
                    _(
                        "Only a maximum of 2 'URL' buttons are allowed per template.",
                    ),
                )

            quick_reply_buttons = buttons.filtered(
                lambda b: b.button_type == "quick_reply",
            )
            if len(quick_reply_buttons) > 3 and (phone_buttons or url_buttons):
                raise ValidationError(
                    _(
                        "Templates combining call or URL buttons only allow up to 3 quick reply buttons.",
                    ),
                )

    @api.constrains("button_type", "name", "phone_number", "url", "url_type", "quick_reply_payload")
    def _check_button_fields(self):
        for button in self:
            if not button.name or not button.name.strip():
                raise ValidationError(_("Button label is required."))
            if len(button.name.strip()) > 25:
                raise ValidationError(
                    _(
                        "Button label '%(name)s' cannot exceed 25 characters (current length: %(length)d).",
                        name=button.name,
                        length=len(button.name.strip()),
                    ),
                )
            if button.button_type == "phone_number":
                if not button.phone_number or not button.phone_number.strip():
                    raise ValidationError(
                        _(
                            "You must specify a phone number for button '%s'.",
                            button.name,
                        ),
                    )
            elif button.button_type == "url":
                if not button.url or not button.url.strip():
                    raise ValidationError(
                        _(
                            "You must specify a website URL for button '%s'.",
                            button.name,
                        ),
                    )
            elif button.button_type == "quick_reply" and button.quick_reply_payload:
                if len(button.quick_reply_payload) > 128:
                    raise ValidationError(
                        _(
                            "Custom payload for button '%(name)s' cannot exceed 128 characters (current length: %(length)d).",
                            name=button.name,
                            length=len(button.quick_reply_payload),
                        ),
                    )

    def _get_rendered_url(self, record=None):
        """Devuelve la URL completa renderizada para un botón dinámico o estático."""
        self.ensure_one()
        return self.template_id._eval_button_dynamic_url(self, record)
