# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.whatsapp_chatter_meta.controllers.webhook import (
    WhatsAppWebhookController,
)


@tagged("post_install", "-at_install")
class TestWhatsAppModernInvoice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.sale_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "sale"),
            ],
            limit=1,
        )
        if not cls.sale_journal:
            cls.sale_journal = cls.env["account.journal"].create(
                {
                    "name": "Customer Invoices Test",
                    "type": "sale",
                    "code": "INVTEST",
                    "company_id": cls.company.id,
                },
            )

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente WhatsApp VIP / S.A.",
                "phone": "+16505551234",
                "email": "vip@example.com",
                "vat": "ESB12345678",
                "street": "Avenida Diagonal 123",
                "city": "Barcelona",
                "lang": "es_ES",
            },
        )

        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "WhatsApp Business Invoice Test",
                "company_id": cls.company.id,
                "phone_number_id": "100000000099991",
                "waba_id": "200000000099992",
                "graph_api_token": "EAAG_TEST_MODERN_INVOICE_TOKEN",
                "webhook_verify_token": "verify_token_modern_inv",
                "app_secret": "app_secret_modern_inv",
            },
        )
        cls.company.whatsapp_account_id = cls.account.id

        acc_rec = cls.env["account.account"].search(
            [
                ("account_type", "=", "asset_receivable"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not acc_rec:
            acc_rec = cls.env["account.account"].create(
                {
                    "name": "Clientes Modern Test",
                    "code": "105999",
                    "account_type": "asset_receivable",
                    "company_ids": [(6, 0, [cls.company.id])],
                },
            )
        cls.partner.property_account_receivable_id = acc_rec.id

        acc_income = cls.env["account.account"].search(
            [
                ("account_type", "=", "income"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not acc_income:
            acc_income = cls.env["account.account"].create(
                {
                    "name": "Ingresos Modern Test",
                    "code": "405999",
                    "account_type": "income",
                    "company_ids": [(6, 0, [cls.company.id])],
                },
            )
        cls.acc_income = acc_income

        cls.product = cls.env["product.product"].create(
            {
                "name": "Licencia Enterprise Anual",
                "type": "service",
                "list_price": 2500.0,
            },
        )

        cls.invoice = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.partner.id,
                "invoice_date": date.today(),
                "invoice_date_due": date.today() + timedelta(days=30),
                "journal_id": cls.sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "account_id": cls.acc_income.id,
                            "quantity": 2.0,
                            "price_unit": 2500.0,
                            "name": "Licencia Enterprise Anual",
                        },
                    ),
                ],
            },
        )
        cls.invoice.action_post()

        # Modern report action
        cls.report_modern = cls.env.ref(
            "whatsapp_chatter_meta.action_report_invoice_whatsapp_modern",
        )

    def test_01_whatsapp_invoice_logo_fallback_and_settings(self):
        """Verifica el fallback del logo de la compañía y la configuración de WhatsApp."""
        # 1. Sin logo WhatsApp específico, retorna el logo general de la compañía
        self.company.whatsapp_invoice_logo = False
        logo = self.company._get_whatsapp_invoice_logo()
        self.assertEqual(logo, self.company.logo)

        # 2. Configurando logo de WhatsApp dedicado
        sample_png = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        self.company.whatsapp_invoice_logo = sample_png
        self.assertEqual(self.company._get_whatsapp_invoice_logo(), sample_png)

        # 3. Verificación de res.config.settings
        settings = self.env["res.config.settings"].create(
            {
                "whatsapp_invoice_logo": sample_png,
            },
        )
        self.assertEqual(settings.whatsapp_invoice_logo, sample_png)

    def test_02_safe_filename_generation(self):
        """Verifica la sanitización inteligente de nombres de archivo para WhatsApp."""
        # Factura con caracteres especiales y partner en español
        self.partner.lang = "es_ES"
        self.invoice.name = "INV/2026/0099#Test!"
        filename_es = self.invoice._get_whatsapp_safe_filename(extension=True)
        self.assertTrue(filename_es.startswith("Factura_"))
        self.assertTrue(filename_es.endswith(".pdf"))
        self.assertNotIn("/", filename_es)
        self.assertNotIn("#", filename_es)
        self.assertNotIn("!", filename_es)
        self.assertNotIn("__", filename_es)

        # Sin extensión
        base_name = self.invoice._get_whatsapp_safe_filename(extension=False)
        self.assertFalse(base_name.endswith(".pdf"))

        # En inglés
        self.partner.lang = "en_US"
        filename_en = self.invoice._get_whatsapp_safe_filename(extension=True)
        self.assertTrue(filename_en.startswith("Invoice_"))
        self.assertTrue(filename_en.endswith(".pdf"))

        # Truncamiento de nombre largo de partner
        self.partner.name = "Empresa Super Extensa con un Nombre Gigantesco que Supera los Limites"
        filename_long = self.invoice._get_whatsapp_safe_filename(extension=True)
        self.assertTrue(len(filename_long) < 80)

        # Tipo nota de crédito
        self.invoice.move_type = "out_refund"
        self.partner.lang = "es_ES"
        filename_refund = self.invoice._get_whatsapp_safe_filename(extension=True)
        self.assertTrue(filename_refund.startswith("NotaCredito_"))

        # Caso borde: Factura en borrador (name = "/") y partner sin nombre
        self.invoice.move_type = "out_invoice"
        self.invoice.name = "/"
        self.partner.name = ""
        filename_draft_empty = self.invoice._get_whatsapp_safe_filename(extension=True)
        self.assertEqual(filename_draft_empty, "Factura_Borrador.pdf")
        self.assertNotIn("__", filename_draft_empty)

        # Múltiples tipos de comprobantes: in_invoice, in_refund, out_receipt
        vendor_partner = self.env["res.partner"].new({"name": "Proveedor SL", "lang": "es_ES"})
        bill = self.env["account.move"].new({
            "move_type": "in_invoice",
            "name": "BILL/2026/01",
            "partner_id": vendor_partner,
        })
        self.assertTrue(bill._get_whatsapp_safe_filename().startswith("FacturaProv_"))

        refund_bill = self.env["account.move"].new({
            "move_type": "in_refund",
            "name": "RBN/2026/01",
            "partner_id": vendor_partner,
        })
        self.assertTrue(refund_bill._get_whatsapp_safe_filename().startswith("NotaCreditoProv_"))

        receipt = self.env["account.move"].new({
            "move_type": "out_receipt",
            "name": "REC/2026/01",
            "partner_id": vendor_partner,
        })
        self.assertTrue(receipt._get_whatsapp_safe_filename().startswith("Recibo_"))

        # Restaurar estado del invoice del setUpClass
        self.invoice.name = "INV/2026/0001"
        self.partner.name = "Cliente WhatsApp VIP / S.A."

    def test_03_smart_caption_calculation(self):
        """Verifica el cálculo dinámico del subtítulo financiero (caption)."""
        self.invoice.move_type = "out_invoice"
        self.partner.lang = "es_ES"
        caption_es = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Factura:", caption_es)
        self.assertIn("Total:", caption_es)
        self.assertIn("Vence:", caption_es)

        # Factura pagada en español
        self.invoice.payment_state = "paid"
        caption_paid_es = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Estado: PAGADA", caption_paid_es)

        # Factura revertida en español
        self.invoice.payment_state = "reversed"
        caption_rev_es = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Estado: REVERTIDA", caption_rev_es)

        # Factura cancelada
        self.invoice.state = "cancel"
        caption_cancel = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Estado: CANCELADA", caption_cancel)
        self.invoice.state = "posted"

        # Factura con pago parcial
        self.invoice.payment_state = "partial"
        self.invoice.amount_residual = 1000.0
        caption_partial = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Saldo:", caption_partial)
        self.assertIn("Total:", caption_partial)

        # Factura en borrador (name = "/")
        self.invoice.name = "/"
        caption_draft = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Borrador", caption_draft)
        self.invoice.name = "INV/2026/0001"

        # En inglés
        self.partner.lang = "en_US"
        self.invoice.payment_state = "not_paid"
        self.invoice.amount_residual = self.invoice.amount_total
        caption_en = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Invoice:", caption_en)
        self.assertIn("Total:", caption_en)
        self.assertIn("Due:", caption_en)

        self.invoice.payment_state = "paid"
        caption_paid_en = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Status: PAID", caption_paid_en)

        self.invoice.payment_state = "reversed"
        caption_rev_en = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Status: REVERSED", caption_rev_en)

        self.invoice.state = "cancel"
        caption_cancel_en = self.invoice._get_whatsapp_invoice_caption()
        self.assertIn("Status: CANCELLED", caption_cancel_en)
        self.invoice.state = "posted"

    def test_04_action_send_whatsapp_invoice_preloads_modern_report(self):
        """Verifica que action_send_whatsapp preseleccione el reporte moderno y metadatos."""
        self.invoice.payment_state = "not_paid"
        self.partner.lang = "es_ES"
        action = self.invoice.action_send_whatsapp()

        self.assertEqual(action["res_model"], "whatsapp.composer.wizard")
        ctx = action["context"]
        self.assertEqual(ctx["default_res_id"], self.invoice.id)
        self.assertEqual(ctx["default_report_action_id"], self.report_modern.id)
        self.assertTrue(ctx["default_pdf_filename"].startswith("Factura_"))
        self.assertTrue(ctx["default_pdf_filename"].endswith(".pdf"))
        self.assertIn("Factura:", ctx["default_caption"])
        self.assertTrue(ctx["default_attach_pdf"])

    def test_05_wizard_pdf_preview_and_fullscreen_action(self):
        """Verifica la generación del preview HTML y la acción de visualización a pantalla completa."""
        action = self.invoice.action_send_whatsapp()
        wizard = (
            self.env["whatsapp.composer.wizard"]
            .with_context(action["context"])
            .create(
                {
                    "res_model": action["context"]["default_res_model"],
                    "res_id": action["context"]["default_res_id"],
                    "account_id": self.account.id,
                    "partner_id": self.partner.id,
                    "phone": "+16505551234",
                    "attach_pdf": True,
                    "report_action_id": self.report_modern.id,
                    "pdf_filename": action["context"]["default_pdf_filename"],
                    "caption": action["context"]["default_caption"],
                },
            )
        )

        wizard._compute_pdf_preview()
        self.assertTrue(wizard.pdf_file_size)
        self.assertTrue(wizard.pdf_preview_html)
        self.assertIn("iframe", wizard.pdf_preview_html)
        self.assertIn("whatsapp_chatter_meta.report_invoice_whatsapp_modern", wizard.pdf_preview_html)
        self.assertIn(str(self.invoice.id), wizard.pdf_preview_html)

        # Probar botón action_view_pdf_fullscreen
        fullscreen_action = wizard.action_view_pdf_fullscreen()
        self.assertEqual(fullscreen_action["type"], "ir.actions.act_url")
        self.assertEqual(fullscreen_action["target"], "new")
        self.assertIn(f"/report/pdf/{self.report_modern.report_name}/{self.invoice.id}", fullscreen_action["url"])

        # Probar badges de estado para cuenta: revertida, cancelada y parcial
        self.invoice.payment_state = "reversed"
        wizard._compute_pdf_preview()
        self.assertIn("REVERTIDA / REVERSED", wizard.pdf_preview_html)

        self.invoice.state = "cancel"
        wizard._compute_pdf_preview()
        self.assertIn("CANCELADA", wizard.pdf_preview_html)
        self.invoice.state = "posted"

        self.invoice.payment_state = "partial"
        wizard._compute_pdf_preview()
        self.assertIn("(Parcial)", wizard.pdf_preview_html)

        # Probar preview y badges para sale.order
        sale_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1.0,
                            "price_unit": 2500.0,
                        },
                    ),
                ],
            },
        )
        wizard_so = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "attach_pdf": True,
            },
        )
        wizard_so._compute_pdf_preview()
        self.assertIn("PRESUPUESTO / QUOTATION", wizard_so.pdf_preview_html)

        sale_order.state = "sale"
        wizard_so._compute_pdf_preview()
        self.assertIn("PEDIDO / SALE ORDER", wizard_so.pdf_preview_html)

    def test_06_modern_qweb_report_rendering_in_memory(self):
        """Verifica que el reporte moderno se renderice en memoria como PDF y contenga los sellos."""
        # 1. Configurar logo de WhatsApp para verificar su renderizado vía image_data_uri
        sample_png = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        self.company.whatsapp_invoice_logo = sample_png

        # Render PDF en memoria sin archivos temporales
        pdf_bytes, _ext = (
            self.env["ir.actions.report"]
            .with_context(report_pdf_no_attachment=True)
            ._render_qweb_pdf(self.report_modern.id, [self.invoice.id])
        )
        self.assertTrue(pdf_bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF") or b"<html" in pdf_bytes or b"<!DOCTYPE" in pdf_bytes)

        # 2. Render HTML para inspeccionar sellos dinámicos y logo
        html_bytes, _ext = (
            self.env["ir.actions.report"]
            ._render_qweb_html(self.report_modern.id, [self.invoice.id])
        )
        html_content = html_bytes.decode("utf-8") if isinstance(html_bytes, bytes) else html_bytes

        # Logo renderizado con data URI
        self.assertIn("data:image/png;base64,", html_content)
        self.assertIn("Company Logo", html_content)

        # Estado pendiente: debe mostrar Vence / Due Date
        self.assertIn("Vence", html_content)
        self.assertIn("Licencia Enterprise Anual", html_content)

        # Descuento en línea de factura
        self.invoice.invoice_line_ids[0].discount = 15.0
        html_disc, _ext = self.env["ir.actions.report"]._render_qweb_html(self.report_modern.id, [self.invoice.id])
        disc_content = html_disc.decode("utf-8") if isinstance(html_disc, bytes) else html_disc
        self.assertIn("Desc:", disc_content)
        self.assertIn("15", disc_content)

        # Estado pagado: debe mostrar sello verde PAGADA / PAID
        self.invoice.payment_state = "paid"
        html_paid, _ext = (
            self.env["ir.actions.report"]
            ._render_qweb_html(self.report_modern.id, [self.invoice.id])
        )
        paid_content = html_paid.decode("utf-8") if isinstance(html_paid, bytes) else html_paid
        self.assertIn("PAGADA / PAID", paid_content)

        # Estado revertido: debe mostrar REVERTIDA / REVERSED
        self.invoice.payment_state = "reversed"
        html_rev, _ext = self.env["ir.actions.report"]._render_qweb_html(self.report_modern.id, [self.invoice.id])
        rev_content = html_rev.decode("utf-8") if isinstance(html_rev, bytes) else html_rev
        self.assertIn("REVERTIDA / REVERSED", rev_content)

        # Estado cancelado: debe mostrar CANCELADA / CANCELLED
        self.invoice.state = "cancel"
        html_cancel, _ext = self.env["ir.actions.report"]._render_qweb_html(self.report_modern.id, [self.invoice.id])
        cancel_content = html_cancel.decode("utf-8") if isinstance(html_cancel, bytes) else html_cancel
        self.assertIn("CANCELADA / CANCELLED", cancel_content)
        self.invoice.state = "posted"

        # Factura en borrador (name = "/")
        self.invoice.name = "/"
        html_draft, _ext = self.env["ir.actions.report"]._render_qweb_html(self.report_modern.id, [self.invoice.id])
        draft_content = html_draft.decode("utf-8") if isinstance(html_draft, bytes) else html_draft
        self.assertIn("Borrador / Draft", draft_content)
        self.invoice.name = "INV/2026/0001"

    def test_07_dispatch_freeform_with_caption_in_payload(self):
        """Verifica que en modo libre el payload de Meta incluya el parámetro caption."""
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "message_mode": "freeform",
                "is_window_open": True,
                "attach_pdf": True,
                "report_action_id": self.report_modern.id,
                "pdf_filename": "Factura_INV_Test.pdf",
                "caption": "📄 Factura: INV/001 | Total: $5,000.00 | Vence: 30/10/2026",
            },
        )

        with (
            patch.object(
                type(self.account),
                "upload_media",
                return_value="meta_media_invoice_001",
            ),
            patch.object(
                type(self.account),
                "dispatch_whatsapp_message",
                return_value="wamid.HBgL_DISPATCH_FREEFORM_CAPTION",
            ) as mock_dispatch,
        ):
            wizard.action_send_whatsapp()

            mock_dispatch.assert_called_once()
            payload = mock_dispatch.call_args[0][0]
            self.assertEqual(payload["type"], "document")
            self.assertEqual(payload["document"]["id"], "meta_media_invoice_001")
            self.assertEqual(payload["document"]["filename"], "Factura_INV_Test.pdf")
            self.assertEqual(
                payload["document"]["caption"],
                "📄 Factura: INV/001 | Total: $5,000.00 | Vence: 30/10/2026",
            )

        # Validar registro en Chatter
        last_message = self.invoice.message_ids[0]
        self.assertIn("Factura_INV_Test.pdf", last_message.body)
        self.assertIn("wamid.HBgL_DISPATCH_FREEFORM_CAPTION", last_message.body)
        self.assertIn("Total: $5,000.00", last_message.body)

        # Validar auditoría en whatsapp.message
        log = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_DISPATCH_FREEFORM_CAPTION")],
            limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log.caption, "📄 Factura: INV/001 | Total: $5,000.00 | Vence: 30/10/2026")

    def test_08_dispatch_template_with_secondary_document_caption(self):
        """Verifica que al enviar plantilla HSM con PDF secundario se envíe el caption."""
        tpl = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_aviso_factura",
                "account_id": self.account.id,
                "model_id": self.env.ref("account.model_account_move").id,
                "language": "es",
                "header_type": "none",
                "body": "Hola estimado cliente, le adjuntamos su factura.",
            },
        )

        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "message_mode": "template",
                "template_id": tpl.id,
                "is_window_open": True,
                "attach_pdf": True,
                "report_action_id": self.report_modern.id,
                "pdf_filename": "Factura_INV_Secundaria.pdf",
                "caption": "📄 Factura Secundaria | Total: $5,000.00",
            },
        )

        dispatched_payloads = []

        def fake_dispatch(account_self, payload):
            dispatched_payloads.append(payload)
            if payload.get("type") == "template":
                return "wamid.HBgL_TPL_PRIMARY"
            return "wamid.HBgL_DOC_SECONDARY"

        with (
            patch.object(
                type(self.account),
                "upload_media",
                return_value="meta_media_sec_002",
            ),
            patch.object(
                type(self.account),
                "dispatch_whatsapp_message",
                side_effect=fake_dispatch,
                autospec=True,
            ),
        ):
            wizard.action_send_whatsapp()

        self.assertEqual(len(dispatched_payloads), 2)
        tpl_msg = dispatched_payloads[0]
        self.assertEqual(tpl_msg["type"], "template")

        doc_msg = dispatched_payloads[1]
        self.assertEqual(doc_msg["type"], "document")
        self.assertEqual(doc_msg["document"]["id"], "meta_media_sec_002")
        self.assertEqual(doc_msg["document"]["filename"], "Factura_INV_Secundaria.pdf")
        self.assertEqual(doc_msg["document"]["caption"], "📄 Factura Secundaria | Total: $5,000.00")

    def test_09_security_xss_sanitization_in_preview_and_chatter(self):
        """Verifica que entradas maliciosas con scripts se saniticen con html_escape."""
        xss_string = "<script>alert('XSS-ATTACK');</script>"
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "is_window_open": True,
                "message_mode": "freeform",
                "attach_pdf": True,
                "report_action_id": self.report_modern.id,
                "pdf_filename": f"Factura_{xss_string}.pdf",
                "caption": f"Resumen {xss_string}",
            },
        )

        wizard._compute_pdf_preview()
        # El HTML generado nunca debe contener scripts sin escapar
        self.assertNotIn("<script>alert('XSS-ATTACK');</script>", wizard.pdf_preview_html)
        self.assertIn("&lt;script&gt;", wizard.pdf_preview_html)

        # Enviar y comprobar el chatter
        with (
            patch.object(
                type(self.account),
                "upload_media",
                return_value="meta_media_xss",
            ),
            patch.object(
                type(self.account),
                "dispatch_whatsapp_message",
                return_value="wamid.HBgL_XSS_SAFE",
            ),
        ):
            wizard.action_send_whatsapp()

        last_message = self.invoice.message_ids[0]
        self.assertNotIn("<script>", str(last_message.body))
        self.assertIn("XSS-ATTACK", str(last_message.body))

    def test_10_inbound_media_with_caption_audit(self):
        """Verifica que un archivo multimedia entrante con caption guarde el caption en whatsapp.message."""
        controller = WhatsAppWebhookController()
        inbound_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": self.account.waba_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "16505550000",
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [{"profile": {"name": "Cliente VIP"}, "wa_id": "16505551234"}],
                                "messages": [
                                    {
                                        "from": "16505551234",
                                        "id": "wamid.HBgL_INBOUND_CAPTION_99",
                                        "timestamp": "1727390000",
                                        "type": "image",
                                        "image": {
                                            "id": "meta_inbound_img_99",
                                            "mime_type": "image/jpeg",
                                            "sha256": "abcdef123456",
                                            "caption": "Comprobante de transferencia bancaria #7890",
                                        },
                                        "context": {
                                            "id": "wamid.HBgL_DISPATCH_FREEFORM_CAPTION",
                                        },
                                    },
                                ],
                            },
                            "field": "messages",
                        },
                    ],
                },
            ],
        }

        raw_body = json.dumps(inbound_payload).encode("utf-8")
        sig = "sha256=" + hmac.new(
            self.account.app_secret.encode("utf-8"), raw_body, hashlib.sha256,
        ).hexdigest()

        mock_req = MagicMock()
        mock_req.env = self.env
        mock_req.httprequest.args = {}
        mock_req.httprequest.headers = {"X-Hub-Signature-256": sig}
        mock_req.httprequest.get_data.return_value = raw_body

        # Mock download_media and request
        with (
            patch("odoo.addons.whatsapp_chatter_meta.controllers.webhook.request", new=mock_req),
            patch.object(
                type(self.account),
                "download_media",
                return_value=(b"fake_jpeg_content", "image/jpeg", "transferencia.jpg"),
            ),
        ):
            resp = controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Verificar que el mensaje entrante fue registrado con su caption
        inbound_msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_INBOUND_CAPTION_99")],
            limit=1,
        )
        self.assertTrue(inbound_msg)
        self.assertEqual(inbound_msg.direction, "inbound")
        self.assertEqual(inbound_msg.caption, "Comprobante de transferencia bancaria #7890")

    def test_11_multicurrency_rendering_and_caption(self):
        """Verifica que una factura en moneda extranjera formatee correctamente símbolos en caption y reporte."""
        usd_currency = self.env.ref("base.USD", raise_if_not_found=False)
        if not usd_currency:
            usd_currency = self.env["res.currency"].search([("name", "=", "USD")], limit=1)
        if not usd_currency:
            usd_currency = self.env["res.currency"].create({"name": "USD", "symbol": "$", "rounding": 0.01})
        usd_currency.active = True

        inv_usd = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "currency_id": usd_currency.id,
                "invoice_date": date.today(),
                "invoice_date_due": date.today() + timedelta(days=15),
                "journal_id": self.sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "account_id": self.acc_income.id,
                            "quantity": 3.0,
                            "price_unit": 1000.0,
                            "name": "Consultoría Internacional USD",
                        },
                    ),
                ],
            },
        )
        inv_usd.action_post()

        # 1. Caption en USD
        self.partner.lang = "es_ES"
        caption = inv_usd._get_whatsapp_invoice_caption()
        self.assertIn(usd_currency.symbol, caption)
        self.assertIn("3,000.00", caption)

        # 2. Render HTML QWeb en USD
        html_bytes, _ext = self.env["ir.actions.report"]._render_qweb_html(self.report_modern.id, [inv_usd.id])
        html_str = html_bytes.decode("utf-8") if isinstance(html_bytes, bytes) else html_bytes
        self.assertIn("Consultoría Internacional USD", html_str)
        self.assertIn(usd_currency.symbol, html_str)
