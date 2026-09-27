# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from markupsafe import escape as html_escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppComposerWizard(models.TransientModel):
    _name = "whatsapp.composer.wizard"
    _description = "WhatsApp Composer Wizard (Meta Cloud API)"

    res_model = fields.Char(string="Document Model", required=True)
    res_id = fields.Integer(string="Document ID", required=True)
    account_id = fields.Many2one(
        "whatsapp.account",
        string="WhatsApp Account",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="account_id.company_id",
        string="Company",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Recipient",
        required=True,
    )
    phone = fields.Char(
        string="Phone (E.164)",
        required=True,
        help="Recipient phone number in international E.164 format (e.g. +16505551234)",
    )
    is_window_open = fields.Boolean(
        string="24h Window Active",
        default=False,
        readonly=True,
        help="Indicates whether the customer has interacted in the last 24 hours allowing freeform messages.",
    )
    message_mode = fields.Selection(
        selection=[
            ("template", "Official Meta Template (HSM)"),
            ("freeform", "Freeform Message (24h Window)"),
        ],
        string="Send Mode",
        default="template",
        required=True,
    )
    template_id = fields.Many2one(
        "whatsapp.template",
        string="WhatsApp Template",
        domain="[('account_id', '=', account_id), ('model', '=', res_model)]",
    )
    has_buttons = fields.Boolean(
        string="Has Buttons",
        compute="_compute_button_preview",
    )
    button_preview_html = fields.Html(
        string="Button Preview",
        compute="_compute_button_preview",
        sanitize=False,
    )
    button_summary = fields.Char(
        string="Button Summary",
        compute="_compute_button_preview",
    )
    body = fields.Text(
        string="Message / Preview",
        help="Message content to send or preview with dynamic variables replaced.",
    )
    attach_pdf = fields.Boolean(
        string="Attach Official PDF",
        default=True,
        help="Compiles official document report in memory and sends it as WhatsApp attachment.",
    )
    report_action_id = fields.Many2one(
        "ir.actions.report",
        string="PDF Report",
    )
    pdf_filename = fields.Char(
        string="PDF Filename",
        default="document.pdf",
    )
    caption = fields.Char(
        string="Document Caption / Subtítulo",
        help="Summary caption sent alongside document attachment to Meta WhatsApp Cloud API.",
    )
    pdf_file_size = fields.Char(
        string="PDF File Size",
        compute="_compute_pdf_preview",
    )
    pdf_preview_html = fields.Html(
        string="PDF Preview",
        compute="_compute_pdf_preview",
        sanitize=False,
    )

    def _get_effective_report(self):
        """Retrieve the effective report action configured or default for model."""
        self.ensure_one()
        report = self.report_action_id
        if not report:
            if self.res_model == "sale.order":
                report = self.env.ref("sale.action_report_saleorder", raise_if_not_found=False)
            elif self.res_model == "account.move":
                report = self.env.ref(
                    "whatsapp_chatter_meta.action_report_invoice_whatsapp_modern",
                    raise_if_not_found=False,
                ) or self.env.ref(
                    "account.account_invoices",
                    raise_if_not_found=False,
                ) or self.env.ref(
                    "account.account_invoices_without_payment",
                    raise_if_not_found=False,
                )
        return report

    def action_view_pdf_fullscreen(self):
        """Action returning act_url to open the rendered PDF report fullscreen in a new tab."""
        self.ensure_one()
        report = self._get_effective_report()
        if not report or not self.res_id:
            raise UserError(_("No report or record available to display."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/report/pdf/{report.report_name}/{self.res_id}",
            "target": "new",
        }

    @api.depends("attach_pdf", "report_action_id", "res_model", "res_id", "pdf_filename")
    def _compute_pdf_preview(self):
        for wizard in self:
            if (
                not wizard.attach_pdf
                or not wizard.res_model
                or not wizard.res_id
                or wizard.res_model not in wizard.env
            ):
                wizard.pdf_preview_html = False
                wizard.pdf_file_size = False
                continue

            record = wizard.env[wizard.res_model].browse(wizard.res_id)
            if not record.exists():
                wizard.pdf_preview_html = False
                wizard.pdf_file_size = False
                continue

            report = wizard._get_effective_report()
            if not report:
                wizard.pdf_preview_html = False
                wizard.pdf_file_size = False
                continue

            filename = wizard.pdf_filename or "document.pdf"
            if not filename.endswith(".pdf"):
                filename = f"{filename}.pdf"

            file_size_display = _("PDF Ready")
            try:
                pdf_content, _report_ext = (
                    wizard.env["ir.actions.report"]
                    .with_context(report_pdf_no_attachment=True)
                    ._render_qweb_pdf(report.id, [record.id])
                )
                if pdf_content:
                    size_bytes = len(pdf_content)
                    if size_bytes < 1024:
                        file_size_display = f"{size_bytes} B"
                    elif size_bytes < 1024 * 1024:
                        file_size_display = f"{size_bytes / 1024:.1f} KB"
                    else:
                        file_size_display = f"{size_bytes / (1024 * 1024):.1f} MB"
            except Exception as e:  # noqa: BLE001
                _logger.debug("PDF preview in-memory render estimation: %s", e)
                file_size_display = _("Ready to generate")

            wizard.pdf_file_size = file_size_display

            badge_html = ""
            if wizard.res_model == "account.move":
                if record.payment_state in ("paid", "in_payment"):
                    badge_html = '<span class="badge bg-success text-white p-2"><i class="fa fa-check-circle me-1"></i>PAGADA / PAID</span>'
                elif record.payment_state == "reversed":
                    badge_html = '<span class="badge bg-dark text-white p-2"><i class="fa fa-undo me-1"></i>REVERTIDA / REVERSED</span>'
                elif record.state == "cancel":
                    badge_html = '<span class="badge bg-danger text-white p-2"><i class="fa fa-ban me-1"></i>CANCELADA</span>'
                elif record.state == "posted":
                    due_date = (
                        record.invoice_date_due.strftime("%d/%m/%Y")
                        if record.invoice_date_due
                        else "N/A"
                    )
                    if record.payment_state == "partial":
                        badge_html = f'<span class="badge bg-warning text-dark p-2"><i class="fa fa-clock-o me-1"></i>Vence: {html_escape(due_date)} (Parcial)</span>'
                    else:
                        badge_html = f'<span class="badge bg-warning text-dark p-2"><i class="fa fa-clock-o me-1"></i>Vence: {html_escape(due_date)}</span>'
                else:
                    badge_html = '<span class="badge bg-secondary text-white p-2">BORRADOR</span>'
            elif wizard.res_model == "sale.order":
                if record.state in ("sale", "done"):
                    badge_html = '<span class="badge bg-success text-white p-2"><i class="fa fa-check-circle me-1"></i>PEDIDO / SALE ORDER</span>'
                elif record.state == "sent":
                    badge_html = '<span class="badge bg-info text-white p-2"><i class="fa fa-paper-plane me-1"></i>ENVIADO / SENT</span>'
                elif record.state == "cancel":
                    badge_html = '<span class="badge bg-danger text-white p-2"><i class="fa fa-ban me-1"></i>CANCELADO / CANCELLED</span>'
                else:
                    badge_html = '<span class="badge bg-secondary text-white p-2">PRESUPUESTO / QUOTATION</span>'

            fullscreen_url = f"/report/pdf/{html_escape(report.report_name)}/{record.id}"
            report_display_name = html_escape(report.name or "")
            clean_filename = html_escape(filename)

            card_html = (
                f'<div class="card border rounded shadow-sm p-3 mb-2 bg-light">'
                f'  <div class="d-flex align-items-center justify-content-between mb-2 pb-2 border-bottom">'
                f'    <div class="d-flex align-items-center">'
                f'      <i class="fa fa-file-pdf-o text-danger fa-2x me-3"></i>'
                f'      <div>'
                f'        <h6 class="mb-0 fw-bold">{clean_filename}</h6>'
                f'        <small class="text-muted">{report_display_name} &bull; {html_escape(file_size_display)}</small>'
                f'      </div>'
                f'    </div>'
                f'    <div class="d-flex align-items-center gap-2">'
                f'      {badge_html}'
                f'      <a href="{fullscreen_url}" target="_blank" class="btn btn-sm btn-outline-primary">'
                f'        <i class="fa fa-external-link me-1"></i>{_("Open Fullscreen PDF")}'
                f'      </a>'
                f'    </div>'
                f'  </div>'
                f'  <div class="rounded border overflow-hidden bg-white" style="height: 380px;">'
                f'    <iframe src="{fullscreen_url}#toolbar=0&navpanes=0" style="width: 100%; height: 100%; border: none;" title="PDF Preview"></iframe>'
                f'  </div>'
                f'</div>'
            )
            wizard.pdf_preview_html = card_html

    @api.depends("template_id", "res_model", "res_id")
    def _compute_button_preview(self):
        for wizard in self:
            template = wizard.template_id
            if not template or not template.button_ids:
                wizard.has_buttons = False
                wizard.button_preview_html = False
                wizard.button_summary = False
                continue

            wizard.has_buttons = True
            record = False
            if wizard.res_model and wizard.res_id and wizard.res_model in wizard.env:
                record = wizard.env[wizard.res_model].browse(wizard.res_id)
                if not record.exists():
                    record = False

            html_chips = []
            summary_parts = []

            for btn in template.button_ids:
                if btn.button_type == "phone_number":
                    html_chips.append(
                        f'<span class="badge rounded-pill bg-light text-dark border me-1 p-2">'
                        f'<i class="fa fa-phone me-1 text-success"></i>{html_escape(btn.name)} ({html_escape(btn.phone_number or "")})</span>',
                    )
                    summary_parts.append(f"{btn.name}: {btn.phone_number or ''}")
                elif btn.button_type == "url":
                    resolved_url = (
                        template._eval_button_dynamic_url(btn, record)
                        if record
                        else (btn.url or "")
                    )
                    html_chips.append(
                        f'<a href="{html_escape(resolved_url)}" target="_blank" class="badge rounded-pill bg-light text-primary border me-1 p-2 text-decoration-none">'
                        f'<i class="fa fa-external-link me-1"></i>{html_escape(btn.name)} <small class="text-muted">({html_escape(resolved_url)})</small></a>',
                    )
                    summary_parts.append(f"{btn.name}: {resolved_url}")
                elif btn.button_type == "quick_reply":
                    payload = btn.quick_reply_payload or btn.name
                    html_chips.append(
                        f'<span class="badge rounded-pill bg-primary text-white me-1 p-2">'
                        f'<i class="fa fa-reply me-1"></i>{html_escape(btn.name)}</span>',
                    )
                    summary_parts.append(f"{btn.name} [{payload}]")

            wizard.button_preview_html = (
                f'<div class="d-flex flex-wrap gap-2 pt-1">{"".join(html_chips)}</div>'
            )
            wizard.button_summary = " | ".join(summary_parts)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            raw_phone = getattr(self.partner_id, "phone", False)
            if not raw_phone and "mobile" in self.partner_id._fields:
                raw_phone = getattr(self.partner_id, "mobile", False)
            raw_phone = raw_phone or ""
            self.phone = self.env["mail.thread"]._format_whatsapp_phone(
                raw_phone, self.partner_id,
            )

    @api.onchange("phone", "partner_id")
    def _onchange_phone_partner(self):
        if self.phone and self.res_model and self.res_id:
            record = self.env[self.res_model].browse(self.res_id)
            if record.exists():
                self.is_window_open = record._is_whatsapp_window_open(phone=self.phone)

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if self.template_id:
            if self.template_id.header_type == "document":
                self.attach_pdf = True
            if self.res_model and self.res_id:
                record = self.env[self.res_model].browse(self.res_id)
                if record.exists():
                    self.body = self.template_id._render_template_body(record)
        else:
            self.body = ""
        self._compute_button_preview()

    @api.onchange("message_mode")
    def _onchange_message_mode(self):
        if self.message_mode == "freeform" and not self.is_window_open:
            self.message_mode = "template"
            return {
                "warning": {
                    "title": _("24-Hour Window Closed"),
                    "message": _(
                        "It is not possible to send a freeform message because the 24-hour customer service window "
                        "is inactive. Meta requires the use of an approved Official Template (HSM).",
                    ),
                },
            }
        return None

    def action_send_whatsapp(self):
        self.ensure_one()
        # 1. Validate phone in E.164 standard
        formatted_phone = self.env["mail.thread"]._format_whatsapp_phone(
            self.phone, self.partner_id,
        )
        if not formatted_phone or len(formatted_phone) < 7:
            raise UserError(
                _(
                    "The phone number provided (%s) is not valid for WhatsApp.",
                    self.phone,
                ),
            )

        recipient_digits = formatted_phone.lstrip("+")

        # 2. Validate message mode against 24-hour window
        if self.message_mode == "freeform" and not self.is_window_open:
            raise UserError(
                _(
                    "The 24-hour service window is not active. "
                    "You must select an Official Meta Template (HSM) to start the conversation.",
                ),
            )

        if self.message_mode == "template" and self.attach_pdf:
            if not self.is_window_open and self.template_id.header_type != "document":
                raise UserError(
                    _(
                        "To attach a PDF outside the 24-hour window, the selected official template must have "
                        "a Document (PDF) header configured. Meta does not allow standalone media messages "
                        "outside the customer service window.",
                    ),
                )

        # 3. Retrieve target record
        if not self.res_model or self.res_model not in self.env:
            raise UserError(
                _("The document model (%s) is not valid.", self.res_model),
            )
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_("The associated record does not exist."))

        # 4. Generate PDF in memory if enabled
        pdf_content = None
        media_id = None
        filename = self.pdf_filename or "document.pdf"
        if not filename.endswith(".pdf"):
            filename = f"{filename}.pdf"

        if self.attach_pdf:
            report = self._get_effective_report()
            if not report:
                raise UserError(
                    _(
                        "No report action found configured to render the PDF.",
                    ),
                )

            # Compilar PDF en memoria sin guardar archivos temporales en disco
            pdf_content, _report_ext = (
                self.env["ir.actions.report"]
                .with_context(report_pdf_no_attachment=True)
                ._render_qweb_pdf(
                    report.id,
                    [record.id],
                )
            )
            if not pdf_content:
                raise UserError(
                    _("An error occurred while rendering the PDF report in memory."),
                )

            if isinstance(pdf_content, str):
                pdf_content = pdf_content.encode("utf-8")

            # Subida directa como multipart/form-data a Meta API (/media)
            account = self.account_id.sudo()
            media_id = account.upload_media(
                filename, pdf_content, mimetype="application/pdf",
            )
        else:
            account = self.account_id.sudo()

        # 5. Despacho a Meta WhatsApp Cloud API
        wamid = False
        secondary_wamid = False
        if self.message_mode == "template":
            template = self.template_id
            if not template:
                raise UserError(
                    _("You must select an official template to continue."),
                )

            # Si la plantilla tiene cabecera de tipo documento y tenemos media_id
            if template.header_type == "document" and media_id:
                components = template._get_meta_components(
                    record, media_id=media_id, filename=filename,
                )
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "template",
                    "template": {
                        "name": template.name,
                        "language": {"code": template.language},
                        "components": components,
                    },
                }
                wamid = account.dispatch_whatsapp_message(payload)
            elif self.attach_pdf and media_id:
                # Si la plantilla no tiene cabecera de documento pero ventana 24h está activa:
                # 1. Despachar plantilla HSM
                components = template._get_meta_components(record)
                tpl_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "template",
                    "template": {
                        "name": template.name,
                        "language": {"code": template.language},
                        "components": components,
                    },
                }
                wamid = account.dispatch_whatsapp_message(tpl_payload)

                # 2. Despachar mensaje de documento con media_id
                doc_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "document",
                    "document": {
                        "id": media_id,
                        "filename": filename,
                    },
                }
                if self.caption:
                    doc_payload["document"]["caption"] = self.caption
                secondary_wamid = account.dispatch_whatsapp_message(doc_payload)
            else:
                components = template._get_meta_components(record)
                tpl_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "template",
                    "template": {
                        "name": template.name,
                        "language": {"code": template.language},
                        "components": components,
                    },
                }
                wamid = account.dispatch_whatsapp_message(tpl_payload)

        else:  # Modo libre (freeform)
            if self.attach_pdf and media_id:
                doc_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "document",
                    "document": {
                        "id": media_id,
                        "filename": filename,
                    },
                }
                doc_caption = self.caption or self.body or ""
                if doc_caption:
                    doc_payload["document"]["caption"] = doc_caption
                wamid = account.dispatch_whatsapp_message(doc_payload)
            else:
                text_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_digits,
                    "type": "text",
                    "text": {
                        "body": self.body or "",
                    },
                }
                wamid = account.dispatch_whatsapp_message(text_payload)

        # 6. Crear adjunto para el Chatter si hubo PDF
        attachment = False
        if pdf_content:
            attachment = self.env["ir.attachment"].create(
                {
                    "name": filename,
                    "type": "binary",
                    "raw": pdf_content,
                    "res_model": record._name,
                    "res_id": record.id,
                    "mimetype": "application/pdf",
                },
            )

        # 7. Registrar mensaje saliente en el Chatter
        id_info = f"<code>{wamid}</code>"
        if secondary_wamid:
            id_info += f", Attachment: <code>{secondary_wamid}</code>"
        header_label = _("Message sent via WhatsApp (%s):", formatted_phone)
        chatter_body = (
            f"<p>📱 <strong>{header_label}</strong></p>"
            f"<p>{html_escape(self.body or '')}</p>"
        )
        if self.caption:
            caption_label = _("Caption:")
            chatter_body += f"<p><small style='color: #495057;'>📄 <strong>{caption_label}</strong> {html_escape(self.caption)}</small></p>"
        if filename:
            file_label = _("File:")
            chatter_body += f"<p><small style='color: #6c757d;'>📎 <strong>{file_label}</strong> {html_escape(filename)}</small></p>"
        if self.message_mode == "template" and self.has_buttons and self.button_summary:
            buttons_label = _("Buttons:")
            chatter_body += f"<p><small style='color: #495057;'>🔘 <strong>{buttons_label}</strong> {html_escape(self.button_summary)}</small></p>"
        chatter_body += f"<p><small style='color: #6c757d;'>WhatsApp Message ID: {id_info}</small></p>"
        record.message_post(
            body=chatter_body,
            attachment_ids=[attachment.id] if attachment else [],
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

        # 8. Guardar auditoría en whatsapp.message
        self.env["whatsapp.message"].sudo().create(
            {
                "wamid": wamid,
                "account_id": self.account_id.id,
                "sender": self.account_id.phone_number_id,
                "recipient": formatted_phone,
                "direction": "outbound",
                "message_type": "document"
                if (self.attach_pdf and not secondary_wamid)
                else ("template" if self.message_mode == "template" else "text"),
                "template_id": self.template_id.id
                if (self.message_mode == "template" and self.template_id)
                else False,
                "body": self.body or "",
                "caption": self.caption or False,
                "attachment_id": attachment.id
                if (attachment and not secondary_wamid)
                else False,
                "media_id": media_id if not secondary_wamid else False,
                "res_model": record._name,
                "res_id": record.id,
                "partner_id": self.partner_id.id,
                "status": "sent",
            },
        )

        if secondary_wamid:
            self.env["whatsapp.message"].sudo().create(
                {
                    "wamid": secondary_wamid,
                    "account_id": self.account_id.id,
                    "sender": self.account_id.phone_number_id,
                    "recipient": formatted_phone,
                    "direction": "outbound",
                    "message_type": "document",
                    "body": filename,
                    "caption": self.caption or False,
                    "attachment_id": attachment.id if attachment else False,
                    "media_id": media_id or False,
                    "res_model": record._name,
                    "res_id": record.id,
                    "partner_id": self.partner_id.id,
                    "status": "sent",
                },
            )

        # 9. Notificación de éxito al usuario
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp Dispatched"),
                "message": _(
                    "The message and attachments were successfully sent to %s.",
                    formatted_phone,
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
