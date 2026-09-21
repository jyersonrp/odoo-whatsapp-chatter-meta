# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo import _, api, fields, models


class WhatsAppMessage(models.Model):
    _name = "whatsapp.message"
    _description = "WhatsApp Message Log (Meta Cloud API)"
    _order = "date desc, id desc"

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    wamid = fields.Char(
        string="WhatsApp Message ID (wamid)",
        required=True,
        index=True,
        copy=False,
        help="Unique message identifier issued or received by Meta",
    )
    account_id = fields.Many2one(
        "whatsapp.account",
        string="WhatsApp Account",
        ondelete="set null",
    )
    company_id = fields.Many2one(
        "res.company",
        related="account_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    template_id = fields.Many2one(
        "whatsapp.template",
        string="HSM Template",
        ondelete="set null",
    )
    date = fields.Datetime(
        string="Date and Time",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    sender = fields.Char(string="Sender", required=True, index=True)
    recipient = fields.Char(string="Recipient", required=True, index=True)
    direction = fields.Selection(
        selection=[
            ("outbound", "Outbound"),
            ("inbound", "Inbound"),
        ],
        string="Direction",
        required=True,
        index=True,
    )
    message_type = fields.Selection(
        selection=[
            ("text", "Text"),
            ("template", "HSM Template"),
            ("document", "Document"),
            ("image", "Image"),
            ("audio", "Audio"),
            ("video", "Video"),
            ("interactive", "Interactive"),
            ("button", "Button"),
            ("other", "Other"),
        ],
        string="Message Type",
        default="text",
    )
    body = fields.Text(string="Content")
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="Attachment",
        ondelete="set null",
    )
    media_id = fields.Char(string="Meta Media ID")
    res_model = fields.Char(string="Related Model", index=True)
    res_id = fields.Integer(string="Record ID", index=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Associated Contact",
        index=True,
        ondelete="set null",
    )
    status = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("read", "Read"),
            ("failed", "Failed"),
            ("received", "Received"),
        ],
        string="Delivery Status",
        default="draft",
        index=True,
    )
    escalated = fields.Boolean(
        string="Escalated to Activity",
        default=False,
        index=True,
    )
    escalation_activity_id = fields.Many2one(
        "mail.activity",
        string="Escalation Activity",
        ondelete="set null",
    )
    error_code = fields.Char(string="Error Code", index=True, readonly=True)
    error_message = fields.Text(string="Error Detail")
    raw_payload = fields.Text(string="Raw JSON Payload")

    @api.depends("wamid", "direction")
    def _compute_name(self):
        for msg in self:
            prefix = "OUT" if msg.direction == "outbound" else "IN"
            short_id = (msg.wamid or "")[-8:]
            msg.name = f"WA-{prefix}-{short_id}"

    def _get_effective_escalation_hours(self):
        self.ensure_one()
        if self.template_id:
            return self.template_id._get_effective_escalation_hours(self.company_id)
        comp = self.company_id or self.env.company
        return getattr(comp, "whatsapp_escalation_hours", 72) or 72

    @api.model
    def cron_escalate_unanswered_messages(self, batch_limit=100):
        """Método público para la ejecución programada de escalamiento."""
        return self._cron_escalate_unanswered_messages(batch_limit=batch_limit)

    @api.model
    def _cron_escalate_unanswered_messages(self, batch_limit=100):
        """
        Escala mensajes salientes desatendidos a actividades de llamada telefónica.
        Monitorea sale.order y account.move con mensajes no respondidos tras el umbral.
        """
        now = fields.Datetime.now()
        processed = self.env["whatsapp.message"]

        candidates = self.search(
            [
                ("direction", "=", "outbound"),
                ("escalated", "=", False),
                ("status", "in", ("sent", "delivered", "read")),
                ("res_model", "in", ("sale.order", "account.move")),
                ("res_id", ">", 0),
            ],
            order="date asc, id asc",
        )

        call_type = self.env.ref(
            "mail.mail_activity_data_call", raise_if_not_found=False,
        )

        for msg in candidates:
            if len(processed) >= batch_limit:
                break

            threshold_hours = msg._get_effective_escalation_hours()
            cutoff = now - timedelta(hours=threshold_hours)
            if not msg.date or msg.date > cutoff:
                continue

            # Verificar si hubo respuesta entrante posterior
            reply_domain = [
                ("direction", "=", "inbound"),
                ("date", ">=", msg.date),
                "|",
                "&",
                ("res_model", "=", msg.res_model),
                ("res_id", "=", msg.res_id),
                ("partner_id", "=", msg.partner_id.id)
                if msg.partner_id
                else ("id", "=", 0),
            ]
            if self.search_count(reply_domain) > 0:
                continue

            record = self.env[msg.res_model].browse(msg.res_id)
            if not record.exists():
                msg.write({"escalated": True})
                processed |= msg
                continue

            # Si el documento está cancelado o pagado, marcar como escalado sin crear actividad
            is_cancelled_so = (
                msg.res_model == "sale.order"
                and getattr(record, "state", False) == "cancel"
            )
            is_paid_or_cancelled_inv = msg.res_model == "account.move" and (
                getattr(record, "state", False) == "cancel"
                or getattr(record, "payment_state", False)
                in ("paid", "in_payment", "reversed")
            )
            if is_cancelled_so or is_paid_or_cancelled_inv:
                msg.write({"escalated": True})
                processed |= msg
                continue

            # Deduplicación: buscar actividad de llamada abierta ya existente en el documento
            existing_activity = False
            if call_type:
                existing_activity = self.env["mail.activity"].search(
                    [
                        ("res_model", "=", msg.res_model),
                        ("res_id", "=", msg.res_id),
                        ("activity_type_id", "=", call_type.id),
                    ],
                    limit=1,
                )

            if existing_activity:
                msg.write(
                    {
                        "escalated": True,
                        "escalation_activity_id": existing_activity.id,
                    },
                )
                processed |= msg
                continue

            # Determinar usuario responsable
            assigned_user = False
            if msg.res_model == "sale.order":
                if record.user_id and record.user_id.active:
                    assigned_user = record.user_id
            elif msg.res_model == "account.move":
                if (
                    hasattr(record, "invoice_user_id")
                    and record.invoice_user_id
                    and record.invoice_user_id.active
                ):
                    assigned_user = record.invoice_user_id
                elif getattr(record, "user_id", False) and record.user_id.active:
                    assigned_user = record.user_id

            if not assigned_user:
                if record.create_uid and record.create_uid.active:
                    assigned_user = record.create_uid
                else:
                    assigned_user = (
                        self.env.ref("base.user_admin", raise_if_not_found=False)
                        or self.env.user
                    )

            # Create call activity
            if msg.res_model == "sale.order":
                summary = _("Unanswered WhatsApp: Commercial Follow-up")
                msg_date_str = msg.date.strftime("%d/%m/%Y %H:%M") if msg.date else ""
                note = _(
                    "<p>Alert: Stalled Communication. The WhatsApp message sent on %s "
                    "has received no reply after the established waiting period.</p>",
                    msg_date_str,
                )
            else:
                summary = _("Unanswered WhatsApp: Collection Management")
                doc_name = record.display_name or ""
                note = _(
                    "<p>Alert: Stalled Communication. Collection management required. "
                    "The WhatsApp message sent for invoice %s has received no reply.</p>",
                    doc_name,
                )

            activity = record.activity_schedule(
                activity_type_id=call_type.id if call_type else False,
                summary=summary,
                note=note,
                user_id=assigned_user.id,
                date_deadline=fields.Date.context_today(record),
            )
            msg.write(
                {
                    "escalated": True,
                    "escalation_activity_id": activity.id if activity else False,
                },
            )
            processed |= msg

        return processed
