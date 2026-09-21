# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsAppComposer(TransactionCase):
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
                    "name": "WhatsApp Sales Journal",
                    "type": "sale",
                    "code": "WHINV",
                    "company_id": cls.company.id,
                },
            )
        cls.country_us = cls.env.ref("base.us")
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente de Prueba",
                "phone": "+1 (650) 555-1234",
                "country_id": cls.country_us.id,
            },
        )
        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "Cuenta Test WhatsApp",
                "company_id": cls.company.id,
                "phone_number_id": "100000000000001",
                "waba_id": "200000000000002",
                "graph_api_token": "EAAG_TEST_TOKEN_12345",
                "webhook_verify_token": "secret_verify_token_xyz",
                "app_secret": "super_secret_app_key_456",
            },
        )
        cls.company.whatsapp_account_id = cls.account.id
        cls.template = cls.env["whatsapp.template"].create(
            {
                "name": "envio_cotizacion",
                "account_id": cls.account.id,
                "model_id": cls.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "document",
                "body": "Hola {{1}}, le enviamos su cotización {{2}} por un total de {{3}}.",
                "variable_mapping": "partner_id.name, name, amount_total",
            },
        )

        # Crear producto y pedido de venta
        cls.product = cls.env["product.product"].create(
            {
                "name": "Servicio de Consultoría",
                "type": "service",
                "list_price": 1500.0,
            },
        )
        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 2.0,
                            "price_unit": 1500.0,
                        },
                    ),
                ],
            },
        )

    def test_01_phone_formatting_e164(self):
        """Verifica que el formateador E.164 limpie y estandarice diversos formatos."""
        thread = self.env["mail.thread"]

        # Con código de país y formato estándar
        p1 = thread._format_whatsapp_phone("+1 (650) 555-1234", self.partner)
        self.assertEqual(p1, "+16505551234")

        # Con prefijo 00
        p2 = thread._format_whatsapp_phone("0034600123456", self.partner)
        self.assertEqual(p2, "+34600123456")

        # Número limpio sin + con código de país del partner
        p3 = thread._format_whatsapp_phone("6505551234", self.partner)
        self.assertEqual(p3, "+16505551234")

    def test_02_24h_window_detection(self):
        """Verifica la detección dinámica de la ventana de atención de 24 horas."""
        # Inicialmente no hay interacción previa
        self.assertFalse(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        # Crear un mensaje entrante reciente (< 24 horas)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.INBOUND_TEST_01",
                "account_id": self.account.id,
                "sender": "16505551234",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "status": "received",
                "partner_id": self.partner.id,
                "date": fields.Datetime.now() - timedelta(hours=2),
            },
        )
        self.assertTrue(self.sale_order._is_whatsapp_window_open(self.partner.phone))

        # Mensaje entrante antiguo (> 24 horas)
        self.env["whatsapp.message"].search([]).write(
            {
                "date": fields.Datetime.now() - timedelta(hours=26),
            },
        )
        self.assertFalse(self.sale_order._is_whatsapp_window_open(self.partner.phone))

    def test_03_template_dynamic_variable_mapping(self):
        """Verifica sustitución de variables dinámicas en plantilla HSM."""
        rendered = self.template._render_template_body(self.sale_order)
        self.assertIn("Cliente de Prueba", rendered)
        self.assertIn(self.sale_order.name, rendered)

    def test_04_action_send_whatsapp_on_sale_order(self):
        """Verifica que el botón en cabecera de sale.order abra el wizard preconfigurado."""
        action = self.sale_order.action_send_whatsapp()
        self.assertEqual(action["res_model"], "whatsapp.composer.wizard")
        self.assertEqual(action["context"]["default_res_id"], self.sale_order.id)
        self.assertEqual(action["context"]["default_partner_id"], self.partner.id)
        self.assertEqual(action["context"]["default_phone"], "+16505551234")
        self.assertTrue(action["context"]["default_attach_pdf"])
        self.assertIn("Quotation_", action["context"]["default_pdf_filename"])

    def test_05_wizard_rejects_freeform_when_window_closed(self):
        """Verifica que el wizard impida enviar mensaje libre si la ventana de 24h está cerrada."""
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "is_window_open": False,
                "message_mode": "freeform",
                "body": "Mensaje fuera de ventana",
                "attach_pdf": False,
            },
        )
        with self.assertRaises(UserError) as cm:
            wizard.action_send_whatsapp()
        self.assertIn(
            "24-hour service window is not active", str(cm.exception),
        )

    @patch(
        "odoo.addons.whatsapp_chatter_meta.models.whatsapp_account.WhatsAppAccount.dispatch_whatsapp_message",
    )
    @patch(
        "odoo.addons.whatsapp_chatter_meta.models.whatsapp_account.WhatsAppAccount.upload_media",
    )
    @patch("odoo.addons.base.models.ir_actions_report.IrActionsReport._render_qweb_pdf")
    def test_06_full_whatsapp_dispatch_with_in_memory_pdf(
        self, mock_render, mock_upload, mock_dispatch,
    ):
        """
        Verifica el flujo completo de envío:
        1. Compilación de PDF en memoria vía _render_qweb_pdf
        2. Subida directa a Meta /media
        3. Despacho del mensaje a Meta Cloud API
        4. Publicación en Chatter con adjunto y wamid
        5. Registro en bitácora whatsapp.message
        """
        fake_pdf_bytes = b"%PDF-1.4 Fake in-memory rendered PDF quote"
        mock_render.return_value = (fake_pdf_bytes, "pdf")
        mock_upload.return_value = "meta_media_id_7777"
        mock_dispatch.return_value = "wamid.HBgL_DISPATCH_SUCCESS_99"

        report = self.env.ref("sale.action_report_saleorder")

        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+1 (650) 555-1234",
                "is_window_open": False,
                "message_mode": "template",
                "template_id": self.template.id,
                "body": "Hola Cliente de Prueba, adjuntamos cotización.",
                "attach_pdf": True,
                "report_action_id": report.id,
                "pdf_filename": "Cotizacion_SO001.pdf",
            },
        )

        initial_msg_count = len(self.sale_order.message_ids)
        wizard.action_send_whatsapp()

        # 1. Comprobar que _render_qweb_pdf fue invocado en memoria
        mock_render.assert_called_once()
        # 2. Comprobar que upload_media recibió el binario exacto en memoria
        mock_upload.assert_called_once()
        self.assertEqual(mock_upload.call_args[0][0], "Cotizacion_SO001.pdf")
        self.assertEqual(mock_upload.call_args[0][1], fake_pdf_bytes)
        # 3. Comprobar despacho a Meta
        mock_dispatch.assert_called_once()

        # 4. Comprobar registro en el Chatter
        self.assertEqual(len(self.sale_order.message_ids), initial_msg_count + 1)
        latest_chatter_msg = self.sale_order.message_ids[0]
        self.assertIn("wamid.HBgL_DISPATCH_SUCCESS_99", latest_chatter_msg.body)
        self.assertTrue(latest_chatter_msg.attachment_ids)
        self.assertEqual(
            latest_chatter_msg.attachment_ids[0].name, "Cotizacion_SO001.pdf",
        )
        self.assertEqual(latest_chatter_msg.attachment_ids[0].raw, fake_pdf_bytes)

        # 5. Comprobar auditoría en whatsapp.message
        wa_log = self.env["whatsapp.message"].search(
            [
                ("wamid", "=", "wamid.HBgL_DISPATCH_SUCCESS_99"),
            ],
            limit=1,
        )
        self.assertTrue(wa_log)
        self.assertEqual(wa_log.direction, "outbound")
        self.assertEqual(wa_log.status, "sent")
        self.assertEqual(wa_log.res_model, "sale.order")
        self.assertEqual(wa_log.res_id, self.sale_order.id)
        self.assertEqual(wa_log.media_id, "meta_media_id_7777")

    def test_07_action_send_whatsapp_on_account_move(self):
        """Verifica que el botón de WhatsApp en facturas abra el wizard con la factura preconfigurada."""
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", self.company.id),
                ("type", "=", "sale"),
            ],
            limit=1,
        )
        if not journal:
            journal = self.env["account.journal"].create(
                {
                    "name": "Facturas de Clientes",
                    "type": "sale",
                    "code": "INV",
                    "company_id": self.company.id,
                },
            )

        # Configurar cuenta por cobrar y cuenta de ingreso si no existen
        acc_rec = self.partner.property_account_receivable_id
        if not acc_rec:
            acc_rec = self.env["account.account"].create(
                {
                    "name": "Clientes",
                    "code": "105001",
                    "account_type": "asset_receivable",
                    "company_ids": [(6, 0, [self.company.id])],
                },
            )
            self.partner.property_account_receivable_id = acc_rec.id

        acc_income = self.env["account.account"].create(
            {
                "name": "Ingresos por Ventas",
                "code": "405001",
                "account_type": "income",
                "company_ids": [(6, 0, [self.company.id])],
            },
        )

        invoice = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "move_type": "out_invoice",
                "journal_id": journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Servicio de Consultoría",
                            "account_id": acc_income.id,
                            "quantity": 1.0,
                            "price_unit": 2000.0,
                        },
                    ),
                ],
            },
        )
        # Plantilla para account.move
        inv_template = self.env["whatsapp.template"].create(
            {
                "name": "envio_factura",
                "account_id": self.account.id,
                "model_id": self.env.ref("account.model_account_move").id,
                "language": "es",
                "header_type": "document",
                "body": "Estimado {{1}}, adjuntamos factura {{2}}.",
                "variable_mapping": "partner_id.name, name",
            },
        )

        action = invoice.action_send_whatsapp()
        self.assertEqual(action["res_model"], "whatsapp.composer.wizard")
        self.assertEqual(action["context"]["default_res_id"], invoice.id)
        self.assertEqual(action["context"]["default_partner_id"], self.partner.id)
        self.assertEqual(action["context"]["default_template_id"], inv_template.id)
        self.assertIn("Cliente de Prueba", action["context"]["default_body"])
        self.assertIn("Invoice_", action["context"]["default_pdf_filename"])
        self.assertTrue(action["context"]["default_attach_pdf"])

    def test_08_partner_mobile_fallback(self):
        """Verifica la resolución y formateo del teléfono del contacto para el wizard (con fallback a mobile si existe)."""
        vals = {
            "name": "Contacto Formato Teléfono",
            "country_id": self.country_us.id,
        }
        if "mobile" in self.env["res.partner"]._fields:
            vals["mobile"] = "+1 (650) 555-8888"
        else:
            vals["phone"] = "+1 (650) 555-8888"
        custom_partner = self.env["res.partner"].create(vals)
        order = self.env["sale.order"].create(
            {
                "partner_id": custom_partner.id,
            },
        )
        phone = order._get_whatsapp_recipient_phone()
        self.assertEqual(phone, "+16505558888")

        action = order.action_send_whatsapp()
        self.assertEqual(action["context"]["default_phone"], "+16505558888")

    test_08_partner_phone_resolution = test_08_partner_mobile_fallback

    def test_09_wizard_rejects_pdf_with_non_document_template_outside_window(self):
        """Verifica que fuera de ventana 24h se rechace adjuntar PDF con plantilla que no tiene cabecera document."""
        nodoc_template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_simple_texto",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Hola {{1}}, aviso sin documento.",
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "is_window_open": False,
                "message_mode": "template",
                "template_id": nodoc_template.id,
                "attach_pdf": True,
            },
        )
        with self.assertRaises(UserError) as cm:
            wizard.action_send_whatsapp()
        self.assertIn("Document (PDF) header configured", str(cm.exception))

    def test_10_template_variable_edge_cases(self):
        """Verifica que campos Many2one no devuelvan el repr técnico y que plantillas sin variables no generen parámetros."""
        # 1. Many2one evaluado debe devolver display_name y no "res.partner(id,)"
        rel_template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_relacional",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Estimado {{1}}",
                "variable_mapping": "partner_id",
            },
        )
        rendered = rel_template._render_template_body(self.sale_order)
        self.assertNotIn("res.partner(", rendered)
        self.assertEqual(rendered, "Estimado Cliente de Prueba")

        # 2. Plantilla estática sin marcadores no debe generar parámetros de cuerpo hacia Meta
        static_template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_estatica",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Gracias por su preferencia.",
            },
        )
        params = static_template._get_template_parameters(self.sale_order)
        self.assertEqual(params, [])
        components = static_template._get_meta_components(self.sale_order)
        self.assertEqual(components, [])

    def test_11_template_buttons_data_model_and_constraints(self):
        """Verifica la creación de botones en plantillas y validación de restricciones de Meta."""
        template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_con_botones",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Mensaje con botones",
                "button_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "button_type": "phone_number",
                            "name": "Llamar a Ventas",
                            "phone_number": "+16505551234",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 20,
                            "button_type": "quick_reply",
                            "name": "Aprobar Presupuesto",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 30,
                            "button_type": "url",
                            "url_type": "dynamic",
                            "name": "Ver Cotización",
                            "url": "https://empresa.com/orders/{{1}}",
                            "url_field_path": "name",
                        },
                    ),
                ],
            },
        )
        self.assertEqual(len(template.button_ids), 3)
        self.assertEqual(template.button_count, 3)

        with self.assertRaises(ValidationError):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": template.id,
                    "button_type": "quick_reply",
                    "name": "Este texto de boton es excesivamente largo para Meta",
                },
            )

        with self.assertRaises(ValidationError):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": template.id,
                    "button_type": "phone_number",
                    "name": "Llamada Sin Teléfono",
                    "phone_number": False,
                },
            )

        with self.assertRaises(ValidationError):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": template.id,
                    "button_type": "url",
                    "name": "Web Sin URL",
                    "url": False,
                },
            )

        with self.assertRaises(ValidationError):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": template.id,
                    "button_type": "phone_number",
                    "name": "Segunda Llamada",
                    "phone_number": "+16505559999",
                },
            )

    def test_12_template_meta_components_serialization(self):
        """Verifica la serialización de componentes de botones hacia la estructura de Meta API."""
        template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_meta_buttons",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Hola {{1}}, pulse los botones abajo.",
                "variable_mapping": "partner_id.name",
                "button_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "button_type": "phone_number",
                            "name": "Llamar Soporte",
                            "phone_number": "+16505551234",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 20,
                            "button_type": "quick_reply",
                            "name": "Aprobar Pedido",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 30,
                            "button_type": "url",
                            "url_type": "dynamic",
                            "name": "Pagar Factura",
                            "url": "https://pay.example.com/pay/{{1}}",
                            "url_field_path": "name",
                        },
                    ),
                ],
            },
        )
        components = template._get_meta_components(self.sale_order)
        body_comp = [c for c in components if c.get("type") == "body"]
        self.assertTrue(body_comp)
        self.assertEqual(body_comp[0]["parameters"][0]["text"], "Cliente de Prueba")

        btn_comps = [c for c in components if c.get("type") == "button"]
        self.assertEqual(
            len(btn_comps),
            2,
            "Solo quick_reply y dynamic url deben generar componentes",
        )

        qr_comp = btn_comps[0]
        self.assertEqual(qr_comp["sub_type"], "quick_reply")
        self.assertEqual(qr_comp["index"], "1")
        self.assertEqual(qr_comp["parameters"][0]["type"], "payload")
        self.assertEqual(qr_comp["parameters"][0]["payload"], "Aprobar Pedido")

        url_comp = btn_comps[1]
        self.assertEqual(url_comp["sub_type"], "url")
        self.assertEqual(url_comp["index"], "2")
        self.assertEqual(url_comp["parameters"][0]["type"], "text")
        self.assertEqual(url_comp["parameters"][0]["text"], self.sale_order.name)

    def test_13_template_meta_components_backward_compatibility(self):
        """Verifica que templates sin botones retornen la estructura previa idéntica a test_06 y test_10."""
        template = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_legacy_sin_botones",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "document",
                "body": "Estimado {{1}}.",
                "variable_mapping": "partner_id.name",
            },
        )
        components = template._get_meta_components(
            self.sale_order, media_id="media_99", filename="doc.pdf",
        )
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]["type"], "header")
        self.assertEqual(components[1]["type"], "body")
        self.assertFalse([c for c in components if c.get("type") == "button"])

    def test_14_wizard_button_preview_rendering(self):
        """Verifica que el wizard calcule y renderice correctamente la vista previa de botones HSM."""
        tpl = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_wizard_preview",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Hola {{1}}, presione un botón:",
                "variable_mapping": "partner_id.name",
                "button_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 1,
                            "button_type": "phone_number",
                            "name": "Llamar a Ventas",
                            "phone_number": "+16505551234",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 2,
                            "button_type": "url",
                            "name": "Ver Pedido",
                            "url_type": "dynamic",
                            "url": "https://miempresa.com/orders/{{1}}",
                            "url_field_path": "name",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 3,
                            "button_type": "quick_reply",
                            "name": "Confirmar",
                            "quick_reply_payload": "CONFIRM_PAYMENT_SO_01",
                        },
                    ),
                ],
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "message_mode": "template",
                "template_id": tpl.id,
            },
        )
        self.assertTrue(wizard.has_buttons)
        self.assertIn("Llamar a Ventas", wizard.button_summary)
        self.assertIn(self.sale_order.name, wizard.button_summary)
        self.assertIn("CONFIRM_PAYMENT_SO_01", wizard.button_summary)
        self.assertIn("badge rounded-pill", wizard.button_preview_html)
        self.assertIn(
            f"https://miempresa.com/orders/{self.sale_order.name}",
            wizard.button_preview_html,
        )

    def test_15_wizard_button_preview_onchange_switching(self):
        """Verifica que cambiar de plantilla en el wizard actualice o limpie la vista previa de botones."""
        tpl_with_btn = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_switch_btn",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Con botones",
                "button_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 1,
                            "button_type": "quick_reply",
                            "name": "Botón 1",
                        },
                    ),
                ],
            },
        )
        tpl_no_btn = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_switch_no_btn",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Sin botones",
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "account_id": self.account.id,
                "partner_id": self.partner.id,
                "phone": "+16505551234",
                "message_mode": "template",
                "template_id": tpl_with_btn.id,
            },
        )
        self.assertTrue(wizard.has_buttons)

        wizard.template_id = tpl_no_btn
        wizard._onchange_template_id()
        self.assertFalse(wizard.has_buttons)
        self.assertFalse(wizard.button_preview_html)
        self.assertFalse(wizard.button_summary)

        wizard.template_id = tpl_with_btn
        wizard._onchange_template_id()
        self.assertTrue(wizard.has_buttons)
        self.assertTrue(wizard.button_preview_html)

    def test_26_quick_reply_payload_constraint(self):
        """Un botón de respuesta rápida con payload > 128 caracteres debe lanzar ValidationError."""
        tpl = self.env["whatsapp.template"].create(
            {
                "name": "plantilla_qr_payload_test",
                "account_id": self.account.id,
                "model_id": self.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "none",
                "body": "Hola",
            },
        )
        with self.assertRaises(ValidationError):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": tpl.id,
                    "button_type": "quick_reply",
                    "name": "Boton Largo",
                    "quick_reply_payload": "X" * 129,
                },
            )

        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": tpl.id,
                "button_type": "quick_reply",
                "name": "Boton OK",
                "quick_reply_payload": "X" * 128,
            },
        )
        self.assertTrue(btn.id)
