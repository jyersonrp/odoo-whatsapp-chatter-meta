# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsAppEscalation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_a.whatsapp_escalation_hours = 72

        cls.company_b = cls.env["res.company"].create(
            {
                "name": "Subsidiaria B Escalamiento Test",
            },
        )

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente Test Escalamiento",
                "phone": "+1 (650) 555-8888",
                "company_id": cls.company_a.id,
            },
        )

        cls.sales_user = cls.env["res.users"].create(
            {
                "name": "Comercial Ventas Escalamiento",
                "login": "sales_rep_esc_test@example.com",
                "email": "sales_rep_esc_test@example.com",
            },
        )

        cls.billing_user = cls.env["res.users"].create(
            {
                "name": "Responsable Cobranzas Escalamiento",
                "login": "billing_rep_esc_test@example.com",
                "email": "billing_rep_esc_test@example.com",
            },
        )

        cls.account_a = cls.env["whatsapp.account"].create(
            {
                "name": "WhatsApp Co A Escalamiento",
                "company_id": cls.company_a.id,
                "phone_number_id": "100000000000088",
                "waba_id": "200000000000088",
                "graph_api_token": "EAAG_TEST_TOKEN_ESC_A",
                "webhook_verify_token": "verify_esc_secret_a",
                "app_secret": "app_secret_esc_key_a",
            },
        )
        cls.company_a.whatsapp_account_id = cls.account_a.id

        model_sale = cls.env["ir.model"].search([("model", "=", "sale.order")], limit=1)
        model_invoice = cls.env["ir.model"].search(
            [("model", "=", "account.move")],
            limit=1,
        )

        # Plantillas con y sin override
        cls.template_standard = cls.env["whatsapp.template"].create(
            {
                "name": "template_standard_default",
                "account_id": cls.account_a.id,
                "model_id": model_sale.id,
                "body": "Hola {{1}}, cotización {{2}} total {{3}}",
                "escalation_hours": 0,
            },
        )

        cls.template_aggressive = cls.env["whatsapp.template"].create(
            {
                "name": "template_aggressive_24h",
                "account_id": cls.account_a.id,
                "model_id": model_invoice.id,
                "body": "Urgente pago {{1}} de factura {{2}}",
                "escalation_hours": 24,
            },
        )

        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "company_id": cls.company_a.id,
                "user_id": cls.sales_user.id,
            },
        )

        cls.sale_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company_a.id),
                ("type", "=", "sale"),
            ],
            limit=1,
        )
        if not cls.sale_journal:
            cls.sale_journal = cls.env["account.journal"].create(
                {
                    "name": "Customer Invoices Test Esc",
                    "type": "sale",
                    "code": "ESCINV",
                    "company_id": cls.company_a.id,
                },
            )

        cls.invoice = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.partner.id,
                "company_id": cls.company_a.id,
                "journal_id": cls.sale_journal.id,
                "invoice_user_id": cls.billing_user.id,
                "invoice_date": fields.Date.today(),
            },
        )

    # -------------------------------------------------------------------------
    # 1. Company & Settings Configuration Tests
    # -------------------------------------------------------------------------
    def test_01_company_default_escalation_hours(self):
        """Verifica que una compañía nueva nazca con 72 horas por defecto."""
        new_co = self.env["res.company"].create({"name": "Nueva Compania Escalamiento"})
        self.assertEqual(
            new_co.whatsapp_escalation_hours,
            72,
            "El valor predeterminado del umbral de escalamiento en res.company debe ser 72 horas.",
        )

    def test_02_res_config_settings_persistence(self):
        """Verifica la persistencia de configuración desde res.config.settings hacia res.company."""
        settings = (
            self.env["res.config.settings"]
            .with_company(self.company_a)
            .create(
                {
                    "whatsapp_escalation_hours": 48,
                },
            )
        )
        settings.execute()

        self.assertEqual(
            self.company_a.whatsapp_escalation_hours,
            48,
            "Al guardar res.config.settings, whatsapp_escalation_hours debe persistir en la compañía activa.",
        )

        reloaded = (
            self.env["res.config.settings"].with_company(self.company_a).create({})
        )
        self.assertEqual(reloaded.whatsapp_escalation_hours, 48)

    def test_03_multi_company_isolation(self):
        """Verifica el aislamiento estricto del umbral entre múltiples compañías."""
        self.company_a.whatsapp_escalation_hours = 36
        self.company_b.whatsapp_escalation_hours = 96

        self.assertEqual(self.company_a.whatsapp_escalation_hours, 36)
        self.assertEqual(self.company_b.whatsapp_escalation_hours, 96)

        settings_a = (
            self.env["res.config.settings"]
            .with_company(self.company_a)
            .create(
                {
                    "whatsapp_escalation_hours": 24,
                },
            )
        )
        settings_a.execute()

        self.assertEqual(self.company_a.whatsapp_escalation_hours, 24)
        self.assertEqual(
            self.company_b.whatsapp_escalation_hours,
            96,
            "Modificar el umbral en la compañía A no debe alterar el umbral de la compañía B.",
        )

    def test_04_template_override_precedence(self):
        """Verifica la precedencia de umbrales entre plantilla y compañía."""
        self.company_a.whatsapp_escalation_hours = 72
        self.assertEqual(
            self.template_aggressive._get_effective_escalation_hours(),
            24,
            "Plantilla con escalation_hours > 0 debe tener precedencia sobre la compañía.",
        )
        self.assertEqual(
            self.template_standard._get_effective_escalation_hours(),
            72,
            "Plantilla con escalation_hours == 0 debe heredar el umbral de la compañía (72h).",
        )

        self.template_standard.escalation_hours = False
        self.assertEqual(
            self.template_standard._get_effective_escalation_hours(),
            72,
            "Plantilla con escalation_hours False debe heredar el umbral de la compañía.",
        )

    def test_05_validation_negative_hours(self):
        """Verifica que valores inválidos lancen ValidationError."""
        with self.assertRaises(ValidationError):
            self.company_a.whatsapp_escalation_hours = -10

        with self.assertRaises(ValidationError):
            self.company_a.whatsapp_escalation_hours = 0

        with self.assertRaises(ValidationError):
            self.template_standard.escalation_hours = -5

    def test_06_message_effective_threshold_resolution(self):
        """Verifica la resolución del umbral efectivo a nivel de mensaje."""
        self.company_a.whatsapp_escalation_hours = 72

        msg_custom = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TEST_MSG_TPL_24",
                "account_id": self.account_a.id,
                "template_id": self.template_aggressive.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
            },
        )
        self.assertEqual(msg_custom._get_effective_escalation_hours(), 24)

        msg_default = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TEST_MSG_TPL_0",
                "account_id": self.account_a.id,
                "template_id": self.template_standard.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
            },
        )
        self.assertEqual(msg_default._get_effective_escalation_hours(), 72)

        msg_freeform = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TEST_MSG_FREEFORM",
                "account_id": self.account_a.id,
                "template_id": False,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
            },
        )
        self.assertEqual(msg_freeform._get_effective_escalation_hours(), 72)

    # -------------------------------------------------------------------------
    # 2. Cron Job & Escalation Processing Tests
    # -------------------------------------------------------------------------
    def test_07_cron_definition_exists_and_active(self):
        """Verifica que el registro ir.cron esté cargado correctamente y activo."""
        cron = self.env.ref(
            "whatsapp_chatter_meta.ir_cron_whatsapp_escalate_unanswered",
            raise_if_not_found=False,
        )
        self.assertTrue(
            cron,
            "El cron ir_cron_whatsapp_escalate_unanswered debe existir en la base de datos.",
        )
        self.assertTrue(cron.active, "El cron debe estar activo por defecto.")
        self.assertEqual(cron.interval_type, "hours")
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.model_id.model, "whatsapp.message")

    def test_08_escalate_stale_unanswered_sale_order(self):
        """Un mensaje saliente de 80h sin respuesta debe escalarse y crear actividad en sale.order."""
        stale_date = fields.Datetime.now() - timedelta(hours=80)
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SO_STALE_80H",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "delivered",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": stale_date,
                "escalated": False,
                "body": "Propuesta de cotización enviada por WhatsApp",
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)
        self.assertTrue(msg.escalation_activity_id)

        call_type = self.env.ref("mail.mail_activity_data_call")
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(len(activities), 1)
        act = activities[0]
        self.assertEqual(act.user_id.id, self.sales_user.id)
        self.assertEqual(act.date_deadline, fields.Date.context_today(self.sale_order))
        self.assertIn("Unanswered WhatsApp", act.summary)
        self.assertIn("Commercial Follow-up", act.summary)
        self.assertIn("Alert: Stalled Communication", act.note)
        self.assertEqual(msg.escalation_activity_id.id, act.id)

    def test_09_escalate_stale_unanswered_account_move(self):
        """Un mensaje saliente de 80h en factura debe escalarse y crear actividad asignada a cobranza."""
        stale_date = fields.Datetime.now() - timedelta(hours=80)
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_INV_STALE_80H",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "read",
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "date": stale_date,
                "escalated": False,
                "body": "Factura enviada por WhatsApp",
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)

        call_type = self.env.ref("mail.mail_activity_data_call")
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", self.invoice.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(len(activities), 1)
        act = activities[0]
        self.assertEqual(act.user_id.id, self.billing_user.id)
        self.assertIn("Collection Management", act.summary)
        self.assertIn("collection", act.note.lower())
        self.assertEqual(msg.escalation_activity_id.id, act.id)

    def test_10_skip_answered_message(self):
        """Un mensaje saliente de 80h con respuesta entrante posterior NO debe escalarse."""
        stale_date = fields.Datetime.now() - timedelta(hours=80)
        out_msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SO_OUT_ANSWERED",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "read",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": stale_date,
                "escalated": False,
            },
        )
        # Respuesta entrante a las 75h (5 horas después)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SO_IN_REPLY_ANSWERED",
                "account_id": self.account_a.id,
                "sender": "+16505558888",
                "recipient": self.account_a.phone_number_id,
                "direction": "inbound",
                "status": "received",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=75),
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertNotIn(out_msg, processed)
        self.assertFalse(out_msg.escalated)

    def test_11_skip_recent_unanswered_message(self):
        """Un mensaje saliente de 10h (< 72h) no debe escalarse todavía."""
        recent_msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_RECENT_10H",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "delivered",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=10),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertNotIn(recent_msg, processed)
        self.assertFalse(recent_msg.escalated)

    def test_12_template_override_stale_triggers_early(self):
        """Mensaje con plantilla de 24h debe escalarse a las 30h aunque la compañía tenga 72h."""
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TPL_EARLY_30H",
                "account_id": self.account_a.id,
                "template_id": self.template_aggressive.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=30),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)

    def test_13_deduplication_multiple_stale_messages_single_record(self):
        """Múltiples mensajes salientes sin respuesta en la misma factura deben generar solo 1 llamada."""
        msg1 = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_INV_MULTI_1",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "read",
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "date": fields.Datetime.now() - timedelta(hours=95),
                "escalated": False,
            },
        )
        msg2 = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_INV_MULTI_2",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "delivered",
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "date": fields.Datetime.now() - timedelta(hours=80),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg1, processed)
        self.assertIn(msg2, processed)
        self.assertTrue(msg1.escalated)
        self.assertTrue(msg2.escalated)
        self.assertEqual(msg1.escalation_activity_id.id, msg2.escalation_activity_id.id)

        call_type = self.env.ref("mail.mail_activity_data_call")
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", self.invoice.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(
            len(activities),
            1,
            "Dos mensajes estancados en la misma factura deben producir solo 1 actividad.",
        )

    def test_14_deduplication_preexisting_call_activity(self):
        """Si la orden ya tenía una llamada abierta, no debe duplicarla y debe marcar el mensaje como escalado."""
        call_type = self.env.ref("mail.mail_activity_data_call")
        preexisting_activity = self.sale_order.activity_schedule(
            activity_type_id=call_type.id,
            summary="Llamada manual previa",
            user_id=self.sales_user.id,
        )

        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PREEXISTING_CALL",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "delivered",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)
        self.assertEqual(msg.escalation_activity_id.id, preexisting_activity.id)

        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(len(activities), 1)

    def test_15_deduplication_allows_call_activity_if_other_type_exists(self):
        """Una actividad pendiente de tipo 'To-Do' o 'Email' no bloquea la creación de 'Call'."""
        todo_type = self.env.ref("mail.mail_activity_data_todo")
        self.sale_order.activity_schedule(
            activity_type_id=todo_type.id,
            summary="Tarea de Seguimiento General",
            user_id=self.sales_user.id,
        )

        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TODO_COEXIST_MSG",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)

        call_type = self.env.ref("mail.mail_activity_data_call")
        call_acts = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(
            len(call_acts),
            1,
            "La actividad de llamada debe coexistir con la actividad de To-Do.",
        )

    def test_16_deduplication_allows_new_call_after_previous_done(self):
        """Si la llamada anterior fue completada (done), un nuevo mensaje frío puede generar una nueva llamada."""
        call_type = self.env.ref("mail.mail_activity_data_call")
        act = self.sale_order.activity_schedule(
            activity_type_id=call_type.id,
            summary="Primera Llamada Realizada",
            user_id=self.sales_user.id,
        )
        act.action_done()

        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_CALL_AFTER_DONE",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)

        active_calls = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
                ("active", "=", True),
            ],
        )
        self.assertEqual(len(active_calls), 1)

    def test_17_no_escalation_for_cancelled_sale_order(self):
        """No se generan actividades de llamada en pedidos de venta cancelados."""
        self.sale_order.action_cancel()

        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SO_CANCEL_SKIP",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)

        call_type = self.env.ref("mail.mail_activity_data_call")
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(
            len(activities),
            0,
            "No debe crearse actividad en pedido cancelado.",
        )

    def test_18_no_escalation_for_paid_invoice(self):
        """No se generan actividades de cobranza en facturas pagadas o revertidas."""
        self.invoice.payment_state = "paid"

        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_INV_PAID_SKIP",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertIn(msg, processed)
        self.assertTrue(msg.escalated)

        call_type = self.env.ref("mail.mail_activity_data_call")
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", self.invoice.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(
            len(activities),
            0,
            "No debe crearse actividad de cobranza en factura pagada.",
        )

    def test_19_skip_inbound_and_failed_messages(self):
        """Mensajes entrantes o fallidos de más de 80h nunca deben ser seleccionados por el cron."""
        in_msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_OLD_INBOUND_SKIP",
                "account_id": self.account_a.id,
                "sender": "+16505558888",
                "recipient": self.account_a.phone_number_id,
                "direction": "inbound",
                "status": "received",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )
        failed_msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_OLD_FAILED_SKIP",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "failed",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertNotIn(in_msg, processed)
        self.assertNotIn(failed_msg, processed)

    def test_20_responsible_user_fallback(self):
        """Verifica la resolución recursiva de usuarios responsables en ausencia o inactividad."""
        # 1. Fallback a creador del registro cuando user_id es False
        salesman_group = self.env.ref("sales_team.group_sale_salesman")
        creator_user = self.env["res.users"].create(
            {
                "name": "Creador del Pedido",
                "login": "creator_user_esc@example.com",
                "email": "creator_user_esc@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, salesman_group.id]),
                ],
            },
        )
        order_with_creator = (
            self.env["sale.order"]
            .with_user(creator_user)
            .create(
                {
                    "partner_id": self.partner.id,
                    "company_id": self.company_a.id,
                    "user_id": False,
                },
            )
        )
        msg1 = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_USER_FALLBACK_SO",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": order_with_creator.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )
        self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertTrue(msg1.escalated)
        self.assertTrue(msg1.escalation_activity_id)
        self.assertEqual(msg1.escalation_activity_id.user_id.id, creator_user.id)

        # 2. Fallback a admin cuando el comercial asignado está inactivo
        inactive_user = self.env["res.users"].create(
            {
                "name": "Usuario Inactivo",
                "login": "inactive_user_esc@example.com",
            },
        )
        inactive_user.write({"active": False})
        order_inactive = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company_a.id,
                "user_id": inactive_user.id,
            },
        )
        msg2 = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_USER_FALLBACK_INACTIVE",
                "account_id": self.account_a.id,
                "sender": self.account_a.phone_number_id,
                "recipient": "+16505558888",
                "direction": "outbound",
                "status": "sent",
                "res_model": "sale.order",
                "res_id": order_inactive.id,
                "date": fields.Datetime.now() - timedelta(hours=85),
                "escalated": False,
            },
        )
        self.env["whatsapp.message"]._cron_escalate_unanswered_messages()
        self.assertTrue(msg2.escalated)
        self.assertTrue(msg2.escalation_activity_id.user_id.active)
        self.assertNotEqual(msg2.escalation_activity_id.user_id.id, inactive_user.id)

    def test_21_batch_limit_pagination(self):
        """El cron debe respetar estrictamente el batch_limit provisto."""
        for i in range(5):
            self.env["whatsapp.message"].create(
                {
                    "wamid": f"wamid.HBgL_PAGINATION_{i}",
                    "account_id": self.account_a.id,
                    "sender": self.account_a.phone_number_id,
                    "recipient": "+16505558888",
                    "direction": "outbound",
                    "status": "sent",
                    "res_model": "sale.order",
                    "res_id": self.sale_order.id,
                    "date": fields.Datetime.now() - timedelta(hours=80 + i),
                    "escalated": False,
                },
            )

        processed = self.env["whatsapp.message"]._cron_escalate_unanswered_messages(
            batch_limit=2,
        )
        self.assertEqual(
            len(processed),
            2,
            "El cron debe retornar exactamente la cantidad indicada por batch_limit.",
        )
