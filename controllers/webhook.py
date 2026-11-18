# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
import logging
import re

from markupsafe import Markup
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
            "WhatsApp handshake failed: invalid verification token or mode (%s).",
            mode,
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

    _STATUS_RANK = {
        "draft": 0,
        "sent": 1,
        "delivered": 2,
        "read": 3,
    }

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

            try:
                with request.env.cr.savepoint():
                    self._process_single_incoming_message(
                        msg, wamid, from_phone, msg_type, contacts, account,
                    )
            except Exception:
                _logger.exception(
                    "Error processing incoming WhatsApp message %s", wamid,
                )

    def _process_single_incoming_message(
        self, msg, wamid, from_phone, msg_type, contacts, account,
    ):
        """Process a single incoming message inside a database savepoint."""
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
            return

        # Extract text content
        body_text = ""
        caption = ""
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
                        "Failed to download WhatsApp media: %s",
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
                f"<p>💬 <strong>{html_escape(header_label)}</strong></p>"
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
                chatter_body += f"<p>📎 <em>{html_escape(media_downloaded)}</em></p>"

            chatter_body += f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{safe_wamid}</code></small></p>"

            attachment_ids = [attachment.id] if attachment else []
            target_record.message_post(
                body=Markup(chatter_body),
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
        wa_msg_model = request.env["whatsapp.message"].sudo()
        wa_msg_model.create(
            {
                "wamid": wamid,
                "account_id": account.id,
                "sender": from_phone,
                "recipient": account.phone_number_id,
                "direction": "inbound",
                "message_type": stored_type,
                "body": body_text,
                "caption": caption or False,
                "res_model": target_record._name if target_record else False,
                "res_id": target_record.id if target_record else False,
                "partner_id": partner.id if partner else False,
                "media_id": str(media_id) if media_id else False,
                "attachment_id": attachment.id if attachment else False,
                "status": "received",
                "raw_payload": json.dumps(msg),
            },
        )

        # Mark prior unanswered outbound messages on this thread/partner as replied
        if "replied" in wa_msg_model._fields and (target_record or partner):
            reply_conds = []
            if target_record:
                reply_conds.append(
                    "&",
                )
                reply_conds.extend(
                    [
                        ("res_model", "=", target_record._name),
                        ("res_id", "=", target_record.id),
                    ],
                )
            if partner:
                if reply_conds:
                    reply_conds = ["|"] + reply_conds + [("partner_id", "=", partner.id)]
                else:
                    reply_conds = [("partner_id", "=", partner.id)]
            unanswered = wa_msg_model.search(
                [
                    ("direction", "=", "outbound"),
                    ("replied", "=", False),
                    ("escalated", "=", False),
                ]
                + reply_conds,
            )
            if unanswered:
                unanswered.write({"replied": True})

    def _find_partner_by_phone(self, phone, company_id=None):
        """Find partner by exact E.164 phone number match first, with country-safe fallback."""
        if not phone:
            return request.env["res.partner"]
        digits = re.sub(r"\D", "", str(phone))
        if not digits:
            return request.env["res.partner"]

        e164_variant = f"+{digits}"
        partner_model = request.env["res.partner"].sudo()

        def _with_company(cond_list):
            dom = ["|"] * (len(cond_list) - 1) + cond_list if len(cond_list) > 1 else list(cond_list)
            if company_id and "company_id" in partner_model._fields:
                dom = ["&", ("company_id", "in", (False, company_id))] + dom
            return dom

        # 1. Exact full E.164 or full digits match (fast index lookup, zero cross-country collision)
        exact_conditions = [("phone", "in", (e164_variant, digits))]
        if "phone_sanitized" in partner_model._fields:
            exact_conditions.append(("phone_sanitized", "in", (e164_variant, digits)))
        if "mobile" in partner_model._fields:
            exact_conditions.append(("mobile", "in", (e164_variant, digits)))

        exact_partner = partner_model.search(
            _with_company(exact_conditions), order="id desc", limit=1,
        )
        if exact_partner:
            return exact_partner

        # 2. Candidate search by tail digits, strictly verified against full E.164 normalization
        tail_conditions = []
        if "phone" in partner_model._fields:
            tail_conditions.append(("phone", "ilike", digits[-10:]))
        if "phone_mobile_search" in partner_model._fields:
            tail_conditions.append(("phone_mobile_search", "ilike", digits[-10:]))
        if "mobile" in partner_model._fields:
            tail_conditions.append(("mobile", "ilike", digits[-10:]))
        if not tail_conditions:
            return request.env["res.partner"]

        candidates = partner_model.search(
            _with_company(tail_conditions), order="id desc", limit=20,
        )
        mail_thread = request.env["mail.thread"]
        fallback_candidate = request.env["res.partner"]

        for cand in candidates:
            raw_phones = [getattr(cand, "phone", False)]
            if "mobile" in cand._fields:
                raw_phones.append(getattr(cand, "mobile", False))
            if "phone_sanitized" in cand._fields:
                raw_phones.append(getattr(cand, "phone_sanitized", False))

            has_explicit_prefix = False
            for raw_p in raw_phones:
                if not raw_p:
                    continue
                raw_str = str(raw_p).strip()
                if raw_str.startswith(("+", "00")):
                    has_explicit_prefix = True
                normalized = mail_thread._format_whatsapp_phone(raw_str, cand)
                if normalized == e164_variant or normalized.lstrip("+") == digits:
                    return cand

            # Only allow tail fallback if candidate had no explicit country prefix (+/00)
            if not has_explicit_prefix and not cand.country_id and not fallback_candidate:
                fallback_candidate = cand

        return fallback_candidate

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

            try:
                with request.env.cr.savepoint():
                    self._process_single_status_update(st, status_wamid, status_val)
            except Exception:
                _logger.exception(
                    "Error processing WhatsApp status update for wamid %s",
                    status_wamid,
                )

    def _process_single_status_update(self, st, status_wamid, status_val):
        """Process a single delivery status update with monotonic state progression."""
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
            return

        # Idempotency: if already in this state, do not repeat alerts or writes
        if msg_record.status == status_val:
            return

        # Prevent out-of-order status regression (e.g. 'delivered' arriving after 'read')
        if status_val != "failed":
            if msg_record.status == "failed":
                return
            current_rank = self._STATUS_RANK.get(msg_record.status, 0)
            incoming_rank = self._STATUS_RANK.get(status_val, 0)
            if incoming_rank < current_rank:
                return

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
                        f"<p>⚠️ <strong>{html_escape(alert_title)}</strong></p>"
                        f"<p>{alert_msg_fmt}</p>"
                        f"<p style='color: #dc3545;'><strong>{html_escape(reason_label)}</strong> {html_escape(full_err)}</p>"
                        f"<p><small style='color: #6c757d;'>WhatsApp Message ID: <code>{safe_status_wamid}</code></small></p>"
                    )
                    doc.message_post(
                        body=Markup(warning_body),
                        message_type="comment",
                        subtype_xmlid="mail.mt_note",
                    )

        msg_record.write(vals)
