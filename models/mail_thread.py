# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re
from datetime import timedelta

from odoo import _, api, fields, models

try:
    from odoo.addons.phone_validation.tools import phone_validation
except ImportError:
    phone_validation = None


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    whatsapp_health_state = fields.Selection(
        selection=[
            ("active", "Active Window"),
            ("expired", "Expired Window"),
            ("cold", "Cold Thread"),
            ("none", "No Conversation"),
        ],
        string="WhatsApp Status",
        compute="_compute_whatsapp_health_state",
        help="24-hour service window and WhatsApp thread health status.",
    )

    def _compute_whatsapp_health_state(self):
        cutoff_24h = fields.Datetime.now() - timedelta(hours=24)
        for record in self:
            if not record.id or not isinstance(record.id, int):
                record.whatsapp_health_state = "none"
                continue

            partner = record._get_whatsapp_recipient_partner()

            # Buscar mensajes asociados al documento específico
            doc_msgs = (
                self.env["whatsapp.message"]
                .sudo()
                .search(
                    [
                        ("res_model", "=", record._name),
                        ("res_id", "=", record.id),
                    ],
                    order="date desc, id desc",
                )
            )

            # Si no hay mensajes específicos del documento, comprobar si hay ventana activa con el contacto
            if not doc_msgs:
                if partner:
                    recent_partner_inbound = (
                        self.env["whatsapp.message"]
                        .sudo()
                        .search_count(
                            [
                                ("partner_id", "=", partner.id),
                                ("direction", "=", "inbound"),
                                ("date", ">=", cutoff_24h),
                            ],
                        )
                    )
                    if recent_partner_inbound > 0:
                        record.whatsapp_health_state = "active"
                        continue
                record.whatsapp_health_state = "none"
                continue

            # 1. Ventana activa: existe mensaje entrante en las últimas 24 horas
            recent_inbound = doc_msgs.filtered(
                lambda m: m.direction == "inbound" and m.date and m.date >= cutoff_24h,
            )
            if recent_inbound:
                record.whatsapp_health_state = "active"
                continue

            # 2. Hilo frío: mensajes salientes consecutivos sin respuesta
            outbounds_since_inbound = 0
            latest_outbound = False
            oldest_outbound = False
            for m in doc_msgs:
                if m.direction == "inbound":
                    break
                if m.direction == "outbound":
                    outbounds_since_inbound += 1
                    if not latest_outbound:
                        latest_outbound = m
                    oldest_outbound = m

            company = getattr(record, "company_id", False) or self.env.company
            escalation_hours = getattr(company, "whatsapp_escalation_hours", 72) or 72
            cutoff_cold = fields.Datetime.now() - timedelta(hours=escalation_hours)
            cutoff_1h = fields.Datetime.now() - timedelta(hours=1)

            is_cold = bool(
                (
                    outbounds_since_inbound >= 2
                    and oldest_outbound
                    and oldest_outbound.date
                    and oldest_outbound.date <= cutoff_1h
                )
                or (
                    latest_outbound
                    and latest_outbound.date
                    and latest_outbound.date <= cutoff_cold
                ),
            )

            if is_cold:
                record.whatsapp_health_state = "cold"
            else:
                record.whatsapp_health_state = "expired"

    def _get_whatsapp_recipient_partner(self):
        """Devuelve el partner principal destinatario de WhatsApp para el registro."""
        self.ensure_one()
        for field_name in ("partner_id", "partner_invoice_id"):
            partner = getattr(self, field_name, False)
            if partner:
                return partner
        return self.env["res.partner"]

    def _get_whatsapp_recipient_phone(self):
        """Devuelve el teléfono del destinatario formateado a E.164 (revisando phone y mobile si existe)."""
        self.ensure_one()
        partner = self._get_whatsapp_recipient_partner()
        phone = False
        if partner:
            phone = getattr(partner, "phone", False)
            if not phone and "mobile" in partner._fields:
                phone = getattr(partner, "mobile", False)
        phone = phone or ""
        return self._format_whatsapp_phone(phone, partner)

    @api.model
    def _format_whatsapp_phone(self, phone, partner=None):
        """Valida y formatea un número telefónico a estándar internacional E.164 (+123456789)."""
        if not phone:
            return ""
        cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
        if not cleaned:
            return ""

        country = (
            partner.country_id
            if (partner and partner.country_id)
            else self.env.company.country_id
        )
        country_code = country.code if country else None
        country_phone_code = country.phone_code if country else None

        if phone_validation:
            try:
                formatted = phone_validation.phone_format(
                    cleaned,
                    country_code=country_code,
                    country_phone_code=country_phone_code,
                    force_format="E164",
                    raise_exception=False,
                )
                if formatted and formatted.startswith("+"):
                    return formatted
            except (ValueError, TypeError):
                pass

        # Fallback de normalización a formato E.164
        if cleaned.startswith("+"):
            return cleaned
        if cleaned.startswith("00"):
            return "+" + cleaned[2:]
        if country_phone_code:
            code_str = str(country_phone_code)
            if cleaned.startswith("0") and not cleaned.startswith("00"):
                cleaned = cleaned.lstrip("0")
            if not cleaned.startswith(code_str):
                return f"+{code_str}{cleaned}"
        return f"+{cleaned}"

    def _is_whatsapp_window_open(self, phone=None):
        """
        Verifica si la ventana de servicio de 24 horas de WhatsApp está abierta
        (ha existido un mensaje entrante del cliente en las últimas 24 horas).
        """
        self.ensure_one()
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        domain = [
            ("direction", "=", "inbound"),
            ("date", ">=", cutoff),
        ]
        partner = self._get_whatsapp_recipient_partner()
        conditions = []
        if partner:
            commercial_id = getattr(partner, "commercial_partner_id", partner).id
            conditions.append(("partner_id", "child_of", commercial_id))
        if phone:
            digits = re.sub(r"\D", "", phone)
            if digits:
                conditions.append(("sender", "like", digits[-10:]))

        if conditions:
            if len(conditions) > 1:
                domain += ["|"] * (len(conditions) - 1) + conditions
            else:
                domain.append(conditions[0])
        else:
            domain += [("res_model", "=", self._name), ("res_id", "=", self.id)]

        return self.env["whatsapp.message"].sudo().search_count(domain) > 0

    def action_open_whatsapp_composer(self):
        """Abre el wizard de WhatsApp para cualquier registro que herede mail.thread."""
        self.ensure_one()
        partner = self._get_whatsapp_recipient_partner()
        phone = self._get_whatsapp_recipient_phone()
        account = self.env["whatsapp.account"]._get_default_account(
            company=getattr(self, "company_id", self.env.company),
        )
        is_window_open = self._is_whatsapp_window_open(phone)

        template = False
        if account:
            template = self.env["whatsapp.template"].search(
                [
                    ("account_id", "=", account.id),
                    ("model", "=", self._name),
                    ("active", "=", True),
                ],
                order="header_type desc, id desc",
                limit=1,
            )
        if not template:
            template = self.env["whatsapp.template"].search(
                [
                    ("model", "=", self._name),
                    ("active", "=", True),
                ],
                order="header_type desc, id desc",
                limit=1,
            )

        default_body = template._render_template_body(self) if template else ""

        return {
            "name": _("Send via WhatsApp"),
            "type": "ir.actions.act_window",
            "res_model": "whatsapp.composer.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_partner_id": partner.id if partner else False,
                "default_phone": phone,
                "default_account_id": account.id if account else False,
                "default_template_id": template.id if template else False,
                "default_body": default_body,
                "default_is_window_open": is_window_open,
                "default_message_mode": "freeform" if is_window_open else "template",
            },
        }
