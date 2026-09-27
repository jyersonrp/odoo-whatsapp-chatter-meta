# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import _, models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _get_whatsapp_safe_filename(self, extension=True):
        """Generate a clean, sanitized, and professional filename for WhatsApp."""
        self.ensure_one()
        lang = (self.partner_id.lang or self.env.lang or "")[:2]

        raw_name = self.name or ""
        clean_name = re.sub(r"[^\w\-]", "_", raw_name).strip("_")
        if not clean_name:
            clean_name = "Borrador" if lang == "es" else "Draft"

        partner_raw = self.partner_id.name or ""
        safe_partner = re.sub(r"[^\w\-]", "_", partner_raw).strip("_")
        if len(safe_partner) > 30:
            safe_partner = safe_partner[:30].rstrip("_")

        if self.move_type == "out_refund":
            prefix = "NotaCredito" if lang == "es" else "CreditNote"
        elif self.move_type == "in_refund":
            prefix = "NotaCreditoProv" if lang == "es" else "VendorCreditNote"
        elif self.move_type == "in_invoice":
            prefix = "FacturaProv" if lang == "es" else "VendorBill"
        elif self.move_type == "out_receipt":
            prefix = "Recibo" if lang == "es" else "Receipt"
        else:
            prefix = "Factura" if lang == "es" else "Invoice"

        if safe_partner:
            base_name = f"{prefix}_{clean_name}_{safe_partner}"
        else:
            base_name = f"{prefix}_{clean_name}"

        base_name = re.sub(r"_+", "_", base_name).strip("_")
        return f"{base_name}.pdf" if extension else base_name

    def _get_whatsapp_invoice_caption(self):
        """Generate a smart financial caption summarizing the invoice for Meta Cloud API."""
        self.ensure_one()
        lang = (self.partner_id.lang or self.env.lang or "")[:2]
        total_str = (
            f"{self.currency_id.symbol} {self.amount_total:,.2f}"
            if self.currency_id
            else f"{self.amount_total:,.2f}"
        )
        residual_str = (
            f"{self.currency_id.symbol} {self.amount_residual:,.2f}"
            if self.currency_id
            else f"{self.amount_residual:,.2f}"
        )

        display_name = (
            self.name
            if self.name and self.name != "/"
            else (_("Borrador") if lang == "es" else _("Draft"))
        )

        if lang == "es":
            due_str = (
                self.invoice_date_due.strftime("%d/%m/%Y")
                if self.invoice_date_due
                else (_("Inmediato") if self.invoice_date else "N/A")
            )
            if self.move_type == "out_refund":
                doc_label = "Nota de Crédito"
            elif self.move_type == "in_refund":
                doc_label = "Nota de Crédito Prov."
            elif self.move_type == "in_invoice":
                doc_label = "Factura Prov."
            elif self.move_type == "out_receipt":
                doc_label = "Recibo"
            else:
                doc_label = "Factura"

            if self.state == "cancel":
                return f"📄 {doc_label}: {display_name} | Total: {total_str} | Estado: CANCELADA"
            if self.payment_state in ("paid", "in_payment"):
                return f"📄 {doc_label}: {display_name} | Total: {total_str} | Estado: PAGADA"
            if self.payment_state == "reversed":
                return f"📄 {doc_label}: {display_name} | Total: {total_str} | Estado: REVERTIDA"
            if self.payment_state == "partial" or (
                self.amount_residual and self.amount_residual != self.amount_total
            ):
                return f"📄 {doc_label}: {display_name} | Total: {total_str} (Saldo: {residual_str}) | Vence: {due_str}"
            return f"📄 {doc_label}: {display_name} | Total: {total_str} | Vence: {due_str}"

        due_str = (
            self.invoice_date_due.strftime("%Y-%m-%d")
            if self.invoice_date_due
            else (_("Immediate") if self.invoice_date else "N/A")
        )
        if self.move_type == "out_refund":
            doc_label = "Credit Note"
        elif self.move_type == "in_refund":
            doc_label = "Vendor Credit Note"
        elif self.move_type == "in_invoice":
            doc_label = "Vendor Bill"
        elif self.move_type == "out_receipt":
            doc_label = "Receipt"
        else:
            doc_label = "Invoice"

        if self.state == "cancel":
            return f"📄 {doc_label}: {display_name} | Total: {total_str} | Status: CANCELLED"
        if self.payment_state in ("paid", "in_payment"):
            return f"📄 {doc_label}: {display_name} | Total: {total_str} | Status: PAID"
        if self.payment_state == "reversed":
            return f"📄 {doc_label}: {display_name} | Total: {total_str} | Status: REVERSED"
        if self.payment_state == "partial" or (
            self.amount_residual and self.amount_residual != self.amount_total
        ):
            return f"📄 {doc_label}: {display_name} | Total: {total_str} (Balance: {residual_str}) | Due: {due_str}"
        return f"📄 {doc_label}: {display_name} | Total: {total_str} | Due: {due_str}"

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

        # Prefer modern WhatsApp invoice report
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

        friendly_filename = self._get_whatsapp_safe_filename(extension=True)
        smart_caption = self._get_whatsapp_invoice_caption()

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
                "Hello %s, we share invoice %s for a total of %s.",
                partner.name or "",
                self.name or "",
                total_str,
            )

        return {
            "name": _("Send Invoice via WhatsApp"),
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
                "default_caption": smart_caption,
                "default_is_window_open": is_window_open,
                "default_message_mode": "freeform" if is_window_open else "template",
            },
        }
