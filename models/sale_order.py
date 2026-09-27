# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import _, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_whatsapp_safe_filename(self, extension=True):
        """Generate a clean, sanitized, and professional filename for WhatsApp."""
        self.ensure_one()
        lang = (self.partner_id.lang or self.env.lang or "")[:2]

        raw_name = self.name or ""
        clean_name = re.sub(r"[^\w\-]", "_", raw_name).strip("_")
        if not clean_name:
            clean_name = "Presupuesto" if lang == "es" else "Quotation"

        partner_raw = self.partner_id.name or ""
        safe_partner = re.sub(r"[^\w\-]", "_", partner_raw).strip("_")
        if len(safe_partner) > 30:
            safe_partner = safe_partner[:30].rstrip("_")

        if self.state in ("sale", "done"):
            prefix = "Pedido" if lang == "es" else "SaleOrder"
        elif self.state == "cancel":
            prefix = "Cancelado" if lang == "es" else "Cancelled"
        else:
            prefix = "Cotizacion" if lang == "es" else "Quotation"

        if safe_partner:
            base_name = f"{prefix}_{clean_name}_{safe_partner}"
        else:
            base_name = f"{prefix}_{clean_name}"

        base_name = re.sub(r"_+", "_", base_name).strip("_")
        return f"{base_name}.pdf" if extension else base_name

    def _get_whatsapp_order_caption(self):
        """Generate a smart commercial caption summarizing the quotation/order for Meta Cloud API."""
        self.ensure_one()
        lang = (self.partner_id.lang or self.env.lang or "")[:2]
        total_str = (
            f"{self.currency_id.symbol} {self.amount_total:,.2f}"
            if self.currency_id
            else f"{self.amount_total:,.2f}"
        )
        display_name = self.name or (_("Presupuesto") if lang == "es" else _("Quotation"))

        if lang == "es":
            validity_str = (
                self.validity_date.strftime("%d/%m/%Y")
                if self.validity_date
                else "30 días"
            )
            if self.state in ("sale", "done"):
                return f"📋 Pedido de Venta: {display_name} | Total: {total_str} | Estado: CONFIRMADO"
            if self.state == "cancel":
                return f"📋 Presupuesto: {display_name} | Total: {total_str} | Estado: CANCELADO"
            return f"📋 Cotización: {display_name} | Total: {total_str} | Validez: {validity_str}"

        validity_str = (
            self.validity_date.strftime("%Y-%m-%d")
            if self.validity_date
            else "30 days"
        )
        if self.state in ("sale", "done"):
            return f"📋 Sale Order: {display_name} | Total: {total_str} | Status: CONFIRMED"
        if self.state == "cancel":
            return f"📋 Quotation: {display_name} | Total: {total_str} | Status: CANCELLED"
        return f"📋 Quotation: {display_name} | Total: {total_str} | Valid Until: {validity_str}"

    def action_send_whatsapp(self):
        self.ensure_one()
        partner = self.partner_id
        raw_phone = (
            getattr(partner, "phone", "")
            or (getattr(partner, "mobile", "") if "mobile" in partner._fields else "")
            or ""
        )
        phone = self._format_whatsapp_phone(raw_phone, partner)
        account = self.env["whatsapp.account"]._get_default_account(
            company=self.company_id,
        )
        is_window_open = self._is_whatsapp_window_open(phone)

        report = self.env.ref(
            "whatsapp_chatter_meta.action_report_saleorder_whatsapp_modern",
            raise_if_not_found=False,
        ) or self.env.ref("sale.action_report_saleorder", raise_if_not_found=False)

        friendly_filename = self._get_whatsapp_safe_filename(extension=True)
        order_caption = self._get_whatsapp_order_caption()

        # Preload corresponding template and rendered text
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

        default_body = ""
        if template:
            default_body = template._render_template_body(self)
        elif is_window_open:
            total_str = (
                f"{self.currency_id.symbol} {self.amount_total:,.2f}"
                if self.currency_id
                else f"{self.amount_total:,.2f}"
            )
            default_body = _(
                "Hello %s, we share quotation %s for a total of %s.",
                partner.name or "",
                self.name or "",
                total_str,
            )

        return {
            "name": _("Send Quotation via WhatsApp"),
            "type": "ir.actions.act_window",
            "res_model": "whatsapp.composer.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_partner_id": partner.id,
                "default_phone": phone,
                "default_account_id": account.id if account else False,
                "default_template_id": template.id if template else False,
                "default_body": default_body,
                "default_attach_pdf": True,
                "default_report_action_id": report.id if report else False,
                "default_pdf_filename": friendly_filename,
                "default_caption": order_caption,
                "default_is_window_open": is_window_open,
                "default_message_mode": "freeform" if is_window_open else "template",
            },
        }
