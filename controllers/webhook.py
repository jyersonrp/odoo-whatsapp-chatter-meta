# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
import logging
import re

from markupsafe import escape as html_escape

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


def _(text, *args, **kwargs):
    if getattr(request, "env", None):
        return request.env._(text, *args, **kwargs)
    return text % args if args else text


class WhatsAppWebhookController(http.Controller):
    @http.route(
        "/whatsapp/webhook",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def webhook_verify(self, **kwargs):
        """
        Handshake de verificación de Meta Graph API (GET).
        Parámetros esperados: hub.mode, hub.verify_token, hub.challenge.
        """
        mode = request.httprequest.args.get("hub.mode") or kwargs.get("hub.mode")
        token = request.httprequest.args.get("hub.verify_token") or kwargs.get(
            "hub.verify_token",
        )
        challenge = request.httprequest.args.get("hub.challenge") or kwargs.get(
            "hub.challenge",
        )

        if mode == "subscribe" and token and challenge:
            account = (
                request.env["whatsapp.account"]
                .sudo()
                .search(
                    [
                        ("webhook_verify_token", "=", token),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
            )

            if account:
                _logger.info(
                    "WhatsApp handshake successful for account: %s",
                    account.name,
                )
                return Response(str(challenge), status=200, content_type="text/plain")

        _logger.warning(
            "WhatsApp handshake failed. mode: %s, provided token: %s",
            mode,
            token,
        )
        return Response("Forbidden", status=403, content_type="text/plain")

    @http.route(
        "/whatsapp/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def webhook_receive(self, **kwargs):
        """
        Receive Meta WhatsApp Cloud API events and messages (POST).
        Validates HMAC-SHA256 signature (X-Hub-Signature-256) against App Secret.
        """
        raw_body = request.httprequest.get_data()
        signature_header = request.httprequest.headers.get("X-Hub-Signature-256", "")

        if not signature_header or not raw_body:
            _logger.warning("WhatsApp Webhook request without signature or empty body.")
            return Response("Invalid signature", status=403, content_type="text/plain")

        # Find active account whose App Secret validates HMAC-SHA256 signature
        active_accounts = (
            request.env["whatsapp.account"].sudo().search([("active", "=", True)])
        )
        matching_account = False

        for account in active_accounts:
            if not account.app_secret:
                continue
            expected_sig = (
                "sha256="
                + hmac.new(
                    account.app_secret.encode("utf-8"),
                    raw_body,
                    hashlib.sha256,
                ).hexdigest()
            )
            if hmac.compare_digest(expected_sig, signature_header):
                matching_account = account
                break

        if not matching_account:
            _logger.warning(
                "Invalid WhatsApp HMAC-SHA256 signature or no matching active account.",
            )
            return Response("Invalid signature", status=403, content_type="text/plain")

        # Process webhook JSON content
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            _logger.error("Error decoding WhatsApp webhook JSON: %s", e)
            return Response(
                json.dumps({"error": "Invalid JSON"}),
                status=400,
                content_type="application/json",
            )

        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if not value:
                        continue

                    # Identify exact account from metadata phone_number_id if available
                    phone_number_id = value.get("metadata", {}).get("phone_number_id")
                    account_for_change = matching_account
                    if phone_number_id:
                        exact_acc = (
                            request.env["whatsapp.account"]
                            .sudo()
                            .search(
                                [
                                    ("phone_number_id", "=", str(phone_number_id)),
                                    ("active", "=", True),
                                ],
                                limit=1,
                            )
                        )
                        if exact_acc and exact_acc.app_secret == matching_account.app_secret:
                            account_for_change = exact_acc

                    # Process incoming messages
                    messages = value.get("messages", [])
                    if messages:
                        self._process_incoming_messages(value, account_for_change)

                    # Process status events (delivery statuses)
                    statuses = value.get("statuses", [])
                    if statuses:
                        self._process_status_updates(statuses, account_for_change)
        except Exception:
            _logger.exception("Unexpected error processing WhatsApp webhook")

        return Response(
            json.dumps({"status": "ok"}),
            status=200,
            content_type="application/json",
        )

    def _process_incoming_messages(self, value, account):
        """Process incoming messages and correlate with Chatter with idempotency control."""
        messages = value.get("messages", [])
        contacts = {
            c.get("wa_id"): c.get("profile", {}).get("name")
            for c in value.get("contacts", [])
        }

        for msg in messages:
            from_phone = msg.get("from", "")
            wamid = msg.get("id", "")
            msg_type = msg.get("type", "text")

            if not wamid:
                continue

            # Idempotency check: ignore duplicate deliveries from Meta
            existing_msg = (
                request.env["whatsapp.message"]
                .sudo()
                .search(
                    [
                        ("wamid", "=", wamid),
                    ],
                    limit=1,
                )
            )
            if existing_msg:
                _logger.info(
                    "WhatsApp message with wamid %s was already processed. Ignoring duplicate.",
                    wamid,
                )
                continue

            # Extract text content
            body_text = ""
            if msg_type == "text":
                body_text = msg.get("text", {}).get("body", "")
            elif msg_type == "button":
                btn = msg.get("button", {})
                body_text = btn.get("text") or btn.get("payload") or ""
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                body_text = (
                    interactive.get("button_reply", {}).get("title")
                    or interactive.get("list_reply", {}).get("title")
                    or interactive.get("button_reply", {}).get("id")
                    or interactive.get("list_reply", {}).get("id")
                    or ""
                )
            elif msg_type in ("image", "document", "audio", "video"):
                media_info = msg.get(msg_type, {})
                caption = media_info.get("caption", "")
                body_text = f"[{msg_type.upper()}] {caption}".strip()
            else:
                body_text = f"[{msg_type}]"

            # 1. Identify contact by phone number
            account_company_id = account.company_id.id if account and account.company_id else None
            partner = self._find_partner_by_phone(from_phone, company_id=account_company_id)

            # 2. Correlate target document
            target_record = False
            prev_msg = False
            context_id = msg.get("context", {}).get("id")

            # a) Correlate by previous quoted message (context.id)
            if context_id:
                prev_msg = (
                    request.env["whatsapp.message"]
                    .sudo()
                    .search(
                        [
                            ("wamid", "=", context_id),
                        ],
                        limit=1,
                    )
                )
                if prev_msg and prev_msg.res_model and prev_msg.res_id:
                    if prev_msg.res_model in request.env:
                        rec = (
                            request.env[prev_msg.res_model]
                            .sudo()
                            .browse(prev_msg.res_id)
                        )
                        if rec.exists():
                            target_record = rec

            # Enrich partner if phone search failed but prev_msg has it
            if not partner and prev_msg and prev_msg.partner_id:
                partner = prev_msg.partner_id
            elif (
                not partner
                and target_record
                and getattr(target_record, "partner_id", False)
            ):
                partner = target_record.partner_id

            # b) Correlate by latest open document of the partner
            if not target_record and partner:
                target_record = self._find_latest_open_document(partner, company_id=account_company_id)

            # c) Fallback to partner record if no open document
            if not target_record and partner:
                target_record = partner

            # Download media file with resilient fallback
            attachment = False
            media_id = False
            download_error = False

            if msg_type in ("image", "document", "audio", "video"):
                media_info = msg.get(msg_type, {})
                media_id = media_info.get("id")
                orig_filename = media_info.get("filename")

                if media_id and account:
                    try:
                        content, mime_type, filename = account.download_media(
                            media_id,
                            filename=orig_filename,
                        )
                        attachment = (
                            request.env["ir.attachment"]
                            .sudo()
                            .create(
                                {
                                    "name": filename,
                                    "raw": content,
                                    "mimetype": mime_type,
                                    "res_model": target_record._name
                                    if target_record
                                    else False,
                                    "res_id": target_record.id
                                    if target_record
                                    else False,
                                },
                            )
                        )
                    except Exception as e:  # noqa: BLE001
                        _logger.warning(
                            "Failed to download WhatsApp media (%s): %s",
                            media_id,
                            e,
                        )
                        download_error = str(e)

            # 3. Post note in target document Chatter
            if target_record:
                author_id = partner.id if partner else False
                author_name = (
                    contacts.get(from_phone) or (partner.name if partner else from_phone)
                )
                safe_from_phone = html_escape(str(from_phone))
                safe_author_name = html_escape(str(author_name))
                safe_wamid = html_escape(str(wamid))

                header_label = _(
                    "Response received via WhatsApp (%s - %s):",
                    safe_from_phone,
                    safe_author_name,
                )
                chatter_body = (
                    f"<p>💬 <strong>{header_label}</strong></p>"
                    f"<p>{html_escape(body_text)}</p>"
                )
                if download_error:
                    media_err_fmt = _(
                        "Media file (%s) could not be downloaded automatically (ID: <code>%s</code>): %s",
                        html_escape(str(msg_type)),
                        html_escape(str(media_id)),
                        html_escape(download_error),
                    )
                    chatter_body += f"<p><span style='color: #dc3545;'>⚠️ {media_err_fmt}</span></p>"
                elif attachment:
                    media_downloaded = _("Media file downloaded and attached automatically.")
                    chatter_body += f"<p>📎 <em>{media_downloaded}</em></p>"

                chatter_body += f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{safe_wamid}</code></small></p>"

                attachment_ids = [attachment.id] if attachment else []
                target_record.message_post(
                    body=chatter_body,
                    author_id=author_id,
                    attachment_ids=attachment_ids,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )

            valid_types = {
                "text",
                "template",
                "document",
                "image",
                "audio",
                "video",
                "interactive",
                "button",
            }
            stored_type = msg_type if msg_type in valid_types else "other"

            # 4. Record audit log in whatsapp.message
            request.env["whatsapp.message"].sudo().create(
                {
                    "wamid": wamid,
                    "account_id": account.id,
                    "sender": from_phone,
                    "recipient": account.phone_number_id,
                    "direction": "inbound",
                    "message_type": stored_type,
                    "body": body_text,
                    "res_model": target_record._name if target_record else False,
                    "res_id": target_record.id if target_record else False,
                    "partner_id": partner.id if partner else False,
                    "media_id": str(media_id) if media_id else False,
                    "attachment_id": attachment.id if attachment else False,
                    "status": "received",
                    "raw_payload": json.dumps(msg),
                },
            )

    def _find_partner_by_phone(self, phone, company_id=None):
        """Find partner by normalized phone number match."""
        if not phone:
            return request.env["res.partner"]
        digits = re.sub(r"\D", "", str(phone))
        if not digits:
            return request.env["res.partner"]

        e164_variant = f"+{digits}"
        partner_model = request.env["res.partner"].sudo()

        conditions = [("phone", "=", e164_variant)]
        if "phone_sanitized" in partner_model._fields:
            conditions.append(("phone_sanitized", "=", e164_variant))
        if "phone" in partner_model._fields:
            conditions.append(("phone", "ilike", digits[-10:]))
        if "phone_mobile_search" in partner_model._fields:
            conditions.append(("phone_mobile_search", "ilike", digits[-10:]))
        if "mobile" in partner_model._fields:
            conditions.append(("mobile", "ilike", digits[-10:]))

        domain = []
        if len(conditions) > 1:
            domain = ["|"] * (len(conditions) - 1) + conditions
        elif conditions:
            domain = conditions

        if company_id and "company_id" in partner_model._fields:
            domain = ["&", ("company_id", "in", (False, company_id))] + domain

        return partner_model.search(domain, limit=1)

    def _find_latest_open_document(self, partner, company_id=None):
        """
        Find latest open document (sale.order or account.move)
        belonging to partner, restricted by company if applicable.
        """
        partner_domain = [("partner_id", "child_of", partner.commercial_partner_id.id)]
        if company_id:
            partner_domain.append(("company_id", "=", company_id))

        # sale.order in draft, sent, or sale state
        recent_sale = (
            request.env["sale.order"]
            .sudo()
            .search(
                partner_domain + [("state", "in", ("draft", "sent", "sale"))],
                order="write_date desc, id desc",
                limit=1,
            )
        )

        # account.move customer invoice in draft or posted unpaid state
        recent_invoice = (
            request.env["account.move"]
            .sudo()
            .search(
                partner_domain
                + [
                    ("move_type", "in", ("out_invoice", "out_refund")),
                    ("state", "in", ("draft", "posted")),
                    ("payment_state", "in", ("not_paid", "partial", "in_payment")),
                ],
                order="write_date desc, id desc",
                limit=1,
            )
        )

        if recent_sale and recent_invoice:
            sale_date = recent_sale.write_date or recent_sale.create_date
            inv_date = recent_invoice.write_date or recent_invoice.create_date
            return recent_sale if sale_date >= inv_date else recent_invoice
        if recent_sale:
            return recent_sale
        if recent_invoice:
            return recent_invoice

        return False

    def _process_status_updates(self, statuses, account):
        """Update delivery statuses (sent, delivered, read, failed) and alert on failure with deduplication."""
        for st in statuses:
            status_wamid = st.get("id", "")
            status_val = st.get("status", "")  # sent, delivered, read, failed
            if not status_wamid or not status_val:
                continue

            msg_record = (
                request.env["whatsapp.message"]
                .sudo()
                .search(
                    [
                        ("wamid", "=", status_wamid),
                    ],
                    limit=1,
                )
            )

            if not msg_record:
                continue

            # Idempotency: if already in this state, do not repeat alerts or writes
            if msg_record.status == status_val:
                continue

            vals = {"status": status_val}

            if status_val == "failed":
                errors = st.get("errors", [])
                err_parts = []
                for err in errors:
                    code = err.get("code", "N/A")
                    title = err.get("title", "Error")
                    details = err.get("details") or err.get("message", "")
                    err_parts.append(f"[{code}] {title}: {details}")

                full_err = (
                    "; ".join(err_parts)
                    or _("Unknown delivery error reported by Meta.")
                )
                vals["error_message"] = full_err
                if errors and errors[0].get("code") is not None:
                    vals["error_code"] = str(errors[0].get("code"))

                # Post alert in original document Chatter
                if (
                    msg_record.res_model
                    and msg_record.res_id
                    and msg_record.res_model in request.env
                ):
                    doc = (
                        request.env[msg_record.res_model]
                        .sudo()
                        .browse(msg_record.res_id)
                    )
                    if doc.exists():
                        safe_recipient = html_escape(str(msg_record.recipient or ""))
                        safe_status_wamid = html_escape(str(status_wamid))
                        alert_title = _("WhatsApp delivery failure:")
                        alert_msg_fmt = _(
                            "The message sent to <strong>%s</strong> could not be delivered.",
                            safe_recipient,
                        )
                        reason_label = _("Reason:")
                        warning_body = (
                            f"<p>⚠️ <strong>{alert_title}</strong></p>"
                            f"<p>{alert_msg_fmt}</p>"
                            f"<p style='color: #dc3545;'><strong>{reason_label}</strong> {html_escape(full_err)}</p>"
                            f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{safe_status_wamid}</code></small></p>"
                        )
                        doc.message_post(
                            body=warning_body,
                            message_type="comment",
                            subtype_xmlid="mail.mt_note",
                        )

            msg_record.write(vals)
