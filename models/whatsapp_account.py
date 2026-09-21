# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import mimetypes
import secrets

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppAccount(models.Model):
    _name = "whatsapp.account"
    _description = "WhatsApp Business Account (Meta Cloud API)"
    _check_company_auto = True

    name = fields.Char(string="Account Name", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    phone_number_id = fields.Char(
        string="Phone Number ID",
        required=True,
        help="Phone number ID provided by Meta WhatsApp Cloud API",
    )
    waba_id = fields.Char(
        string="WABA ID",
        required=True,
        help="WhatsApp Business Account ID",
    )
    graph_api_token = fields.Char(
        string="Access Token (Bearer)",
        required=True,
        groups="base.group_system",
        help="Permanent or system user access token generated in Meta Business Manager",
    )
    api_version = fields.Char(
        string="Graph API Version",
        required=True,
        default="v21.0",
        help="Meta Graph API version (e.g. v21.0)",
    )
    webhook_verify_token = fields.Char(
        string="Webhook Verify Token",
        required=True,
        default=lambda self: secrets.token_hex(16),
        groups="base.group_system",
        help="Verification token used in Meta Webhook GET handshake",
    )
    app_secret = fields.Char(
        string="App Secret",
        required=True,
        groups="base.group_system",
        help="Meta application secret to validate webhook HMAC-SHA256 signature",
    )
    active = fields.Boolean(string="Active", default=True)

    def _get_api_url(self, endpoint=""):
        self.ensure_one()
        version = self.api_version or "v21.0"
        clean_endpoint = endpoint.lstrip("/")
        return f"https://graph.facebook.com/{version}/{clean_endpoint}"

    def _get_headers(self, is_json=True):
        self.ensure_one()
        token = self.sudo().graph_api_token
        headers = {
            "Authorization": f"Bearer {token}",
        }
        if is_json:
            headers["Content-Type"] = "application/json"
        return headers

    def action_test_connection(self):
        self.ensure_one()
        sudo_self = self.sudo()
        if not sudo_self.phone_number_id or not sudo_self.graph_api_token:
            raise UserError(
                _("You must configure Phone Number ID and Access Token."),
            )

        url = sudo_self._get_api_url(sudo_self.phone_number_id)
        headers = {
            "Authorization": f"Bearer {sudo_self.graph_api_token}",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
        except requests.RequestException as e:
            _logger.error("Error connecting to Meta Graph API: %s", e)
            raise UserError(
                _("Could not establish connection with Meta Graph API: %s", str(e)),
            )

        if response.status_code == 200:
            # Automatically subscribe app to WABA events
            if self.waba_id:
                try:
                    sub_url = self._get_api_url(f"{self.waba_id}/subscribed_apps")
                    requests.post(sub_url, headers=headers, timeout=5)
                except requests.RequestException as e:
                    _logger.warning(
                        "Could not automatically subscribe app to WABA: %s",
                        e,
                    )

            data = response.json()
            display_phone = data.get("display_phone_number", self.phone_number_id)
            verified_name = data.get("verified_name", "Verified")
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Successful"),
                    "message": _(
                        "Connection to Meta Cloud API validated successfully. Phone: %s (%s)",
                        display_phone,
                        verified_name,
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }
        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", response.text)
            err_code = err_data.get("code", response.status_code)
        except (ValueError, KeyError, TypeError):
            err_msg = response.text
            err_code = response.status_code
        _logger.warning(
            "Failed to test WhatsApp connection (%s): %s",
            err_code,
            err_msg,
        )
        raise UserError(
            _(
                "Failed to test connection with Meta (Code %s): %s",
                err_code,
                err_msg,
            ),
        )

    @api.model
    def _get_default_account(self, company=None, raise_exception=False):
        company = company or self.env.company
        if (
            company
            and company.whatsapp_account_id
            and company.whatsapp_account_id.active
        ):
            return company.whatsapp_account_id
        account = self.search(
            [("company_id", "=", company.id), ("active", "=", True)],
            order="id desc",
            limit=1,
        )
        if not account and not raise_exception:
            # Fallback to any active account without company or any active account
            account = self.search([("active", "=", True)], order="id desc", limit=1)
        if not account and raise_exception:
            raise UserError(
                _(
                    "No active WhatsApp account configured for company %s.",
                    company.name,
                ),
            )
        return account

    def upload_media(self, filename, file_content, mimetype="application/pdf"):
        """
        Sube un binario directamente en memoria como multipart/form-data a Meta Cloud API.
        Endpoint: POST https://graph.facebook.com/{version}/{phone_number_id}/media
        """
        self.ensure_one()
        url = self._get_api_url(f"{self.phone_number_id}/media")
        headers = self._get_headers(is_json=False)
        files = {
            "file": (filename, file_content, mimetype),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mimetype,
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=30,
            )
        except requests.RequestException as e:
            _logger.error("Network error uploading media file to WhatsApp: %s", e)
            raise UserError(_("Network error uploading file to WhatsApp: %s", str(e)))

        if response.status_code == 200:
            res_data = response.json()
            media_id = res_data.get("id")
            if not media_id:
                raise UserError(
                    _("Meta did not return a valid media ID: %s", response.text),
                )
            _logger.info(
                "File %s successfully uploaded to Meta with media_id: %s",
                filename,
                media_id,
            )
            return media_id
        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", response.text)
            err_code = err_data.get("code", response.status_code)
        except (ValueError, KeyError, TypeError):
            err_msg = response.text
            err_code = response.status_code
        _logger.error(
            "Meta error uploading media file (%s): %s",
            err_code,
            err_msg,
        )
        raise UserError(_("Meta error uploading file (%s): %s", err_code, err_msg))

    def dispatch_whatsapp_message(self, payload):
        """
        Despacha un mensaje a Meta WhatsApp Cloud API.
        Endpoint: POST https://graph.facebook.com/{version}/{phone_number_id}/messages
        """
        self.ensure_one()
        url = self._get_api_url(f"{self.phone_number_id}/messages")
        headers = self._get_headers(is_json=True)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
        except requests.RequestException as e:
            _logger.error("Network error dispatching WhatsApp message: %s", e)
            raise UserError(_("Network error sending WhatsApp message: %s", str(e)))

        if response.status_code in (200, 201):
            res_data = response.json()
            messages = res_data.get("messages", [])
            if messages and "id" in messages[0]:
                return messages[0]["id"]
            raise UserError(
                _("Unexpected response from Meta sending message: %s", response.text),
            )
        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", response.text)
            err_code = err_data.get("code", response.status_code)
        except (ValueError, KeyError, TypeError):
            err_msg = response.text
            err_code = response.status_code
        _logger.error("Meta error sending message (%s): %s", err_code, err_msg)
        raise UserError(
            _("Meta error sending message (%s): %s", err_code, err_msg),
        )

    def get_media_url(self, media_id):
        """
        Consulta la URL temporal de descarga de un archivo multimedia desde Meta Cloud API.
        Endpoint: GET https://graph.facebook.com/{version}/{media_id}
        Retorna: str (download_url)
        """
        self.ensure_one()
        url = self._get_api_url(str(media_id))
        headers = self._get_headers(is_json=True)

        try:
            response = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            _logger.error(
                "Network error querying media URL on Meta (%s): %s",
                media_id,
                e,
            )
            raise UserError(
                _(
                    "Network error querying media file on WhatsApp: %s",
                    str(e),
                ),
            )

        if response.status_code == 200:
            data = response.json()
            download_url = data.get("url")
            if not download_url:
                raise UserError(
                    _(
                        "Meta did not return a download URL for media_id %s",
                        media_id,
                    ),
                )
            return download_url

        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", response.text)
            err_code = err_data.get("code", response.status_code)
        except (ValueError, KeyError, TypeError):
            err_msg = response.text
            err_code = response.status_code
        _logger.error(
            "Meta error retrieving media URL (%s): %s",
            err_code,
            err_msg,
        )
        raise UserError(
            _(
                "Meta error retrieving media URL (%s): %s",
                err_code,
                err_msg,
            ),
        )

    def download_media(self, media_id, filename=None):
        """
        Descarga el binario de un archivo multimedia desde Meta Lookaside CDN.
        Retorna: tuple (bytes_content, mime_type, resolved_filename)
        """
        self.ensure_one()
        media_url_res = self.get_media_url(media_id)
        if isinstance(media_url_res, (list, tuple)):
            download_url = media_url_res[0]
            mime_type = media_url_res[1] if len(media_url_res) > 1 else None
        else:
            download_url = media_url_res
            mime_type = None

        # Meta requiere header Authorization con Bearer token y User-Agent
        token = self.sudo().graph_api_token
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Odoo-WhatsApp-Client/1.0",
        }

        try:
            response = requests.get(download_url, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.error(
                "Network error downloading binary from Meta CDN (%s): %s",
                media_id,
                e,
            )
            raise UserError(
                _("Network error downloading file from Meta: %s", str(e)),
            )

        if response.status_code == 200:
            content = response.content
            if not mime_type or not isinstance(mime_type, str):
                resp_headers = getattr(response, "headers", None)
                if resp_headers and hasattr(resp_headers, "get"):
                    content_type = resp_headers.get("Content-Type")
                    if isinstance(content_type, str):
                        mime_type = content_type.split(";")[0].strip()
            if (not mime_type or not isinstance(mime_type, str)) and filename:
                guessed_mime, _enc = mimetypes.guess_type(filename)
                if guessed_mime:
                    mime_type = guessed_mime
            if not mime_type or not isinstance(mime_type, str):
                mime_type = "application/octet-stream"

            if not filename:
                ext = mimetypes.guess_extension(mime_type) or ""
                if ext == ".jpe":
                    ext = ".jpg"
                if not ext:
                    if "image" in mime_type:
                        ext = ".jpg"
                    elif "pdf" in mime_type:
                        ext = ".pdf"
                    elif "audio" in mime_type:
                        ext = ".ogg"
                    elif "video" in mime_type:
                        ext = ".mp4"
                filename = f"whatsapp_{media_id}{ext}"
            return content, mime_type, filename

        _logger.error(
            "Error downloading file from Meta CDN. Code: %s",
            response.status_code,
        )
        raise UserError(
            _(
                "Error downloading file from Meta CDN (Code %s)",
                response.status_code,
            ),
        )
