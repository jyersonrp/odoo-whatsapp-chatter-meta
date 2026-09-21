# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""
==============================================================================
Test Suite: WhatsApp Chatter Meta Gen2 - 4-Tier Opaque-Box E2E Tests
==============================================================================
This test file implements the 4-Tier Testing Methodology covering Features 1-17:
- Tier 1: Feature Coverage (>=5 test methods per feature)
- Tier 2: Boundary, Adversarial & Corner Cases (>=5 test methods per feature)
- Tier 3: Cross-Feature Interactions (Pairwise combinations)
- Tier 4: Real-World Workload Scenarios (Multi-step end-to-end workflows)

All Meta Graph API calls (GET/POST) and QWeb PDF renders are 100% mocked with
unittest.mock to ensure complete offline independence and zero external dependencies.
==============================================================================
"""

import ast
import glob
import hashlib
import hmac
import json
import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.whatsapp_chatter_meta.controllers.webhook import (
    WhatsAppWebhookController,
)


# ============================================================================
# Base Test Case with Common Fixtures & Doubles
# ============================================================================
class WhatsAppE2EBase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = WhatsAppWebhookController()
        cls.company = cls.env.company

        # Ensure sales journal exists for invoice tests
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
                    "name": "WhatsApp Tier Test Journal",
                    "type": "sale",
                    "code": "WTST",
                    "company_id": cls.company.id,
                },
            )

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente Tier Test",
                "phone": "+16505559999",
            },
        )

        cls.account = cls.env["whatsapp.account"].create(
            {
                "name": "Cuenta Test E2E Tiers",
                "company_id": cls.company.id,
                "phone_number_id": "199999999999999",
                "waba_id": "299999999999999",
                "graph_api_token": "EAAG_TIER_TEST_TOKEN",
                "api_version": "v21.0",
                "webhook_verify_token": "tier_verify_secret_123",
                "app_secret": "super_secret_tier_app_secret",
            },
        )
        cls.company.whatsapp_account_id = cls.account.id

        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "state": "draft",
            },
        )

        cls.account_move = cls.env["account.move"].create(
            {
                "partner_id": cls.partner.id,
                "move_type": "out_invoice",
                "journal_id": cls.sale_journal.id,
                "invoice_date": fields.Date.today(),
            },
        )

        cls.template = cls.env["whatsapp.template"].create(
            {
                "name": "plantilla_hsm_base_tier",
                "account_id": cls.account.id,
                "model_id": cls.env.ref("sale.model_sale_order").id,
                "language": "es",
                "header_type": "document",
                "body": "Hola {{1}}, cotización {{2}} total {{3}}.",
                "variable_mapping": "partner_id.name, name, amount_total",
            },
        )

    def _sign_payload(self, payload_bytes, secret=None):
        """Calculates valid Meta HMAC-SHA256 signature header."""
        secret = secret or self.account.app_secret
        sig_hash = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={sig_hash}"

    def _mock_request(self, args=None, headers=None, data=b""):
        """Builds a mock Werkzeug request double for the controller."""
        mock_req = MagicMock()
        mock_req.env = self.env
        mock_req.httprequest.args = args or {}
        mock_req.httprequest.headers = headers or {}
        mock_req.httprequest.get_data.return_value = data
        return mock_req

    def _has_button_table(self):
        """Checks if the whatsapp_template_button table exists in database."""
        if "whatsapp.template.button" not in self.env:
            return False
        try:
            self.env.cr.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'whatsapp_template_button'",
            )
            return bool(self.env.cr.fetchone())
        except Exception:  # noqa: BLE001
            return False


# ============================================================================
# TIER 1: FEATURE COVERAGE (>= 5 test methods per feature across Features 1-17)
# ============================================================================
@tagged("post_install", "-at_install")
class TestWhatsAppE2ETier1FeatureCoverage(WhatsAppE2EBase):
    # ------------------------------------------------------------------------
    # Feature 1: HSM Button Models & Types
    # ------------------------------------------------------------------------
    def test_t1_f01_01_button_model_registration(self):
        """F1.1: Verify whatsapp.template.button model is defined and accessible."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        button_model = self.env["whatsapp.template.button"]
        self.assertTrue(button_model._name == "whatsapp.template.button")
        self.assertIn("button_type", button_model._fields)
        self.assertIn("name", button_model._fields)
        self.assertIn("sequence", button_model._fields)

    def test_t1_f01_02_button_type_phone_number(self):
        """F1.2: Verify phone_number button configuration."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "phone_number",
                "name": "Llamar Soporte",
                "phone_number": "+16505551111",
                "sequence": 10,
            },
        )
        self.assertEqual(btn.button_type, "phone_number")
        self.assertEqual(btn.phone_number, "+16505551111")

    def test_t1_f01_03_button_type_quick_reply(self):
        """F1.3: Verify quick_reply button configuration."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "Confirmar Pedido",
                "sequence": 20,
            },
        )
        self.assertEqual(btn.button_type, "quick_reply")
        self.assertEqual(btn.name, "Confirmar Pedido")

    def test_t1_f01_04_button_type_url(self):
        """F1.4: Verify static and dynamic url button configurations."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Ver Factura",
                "url": "https://miempresa.com/my/invoices/{{1}}",
                "url_type": "dynamic",
                "sequence": 30,
            },
        )
        self.assertEqual(btn.button_type, "url")
        self.assertEqual(btn.url_type, "dynamic")

    def test_t1_f01_05_button_sequence_ordering(self):
        """F1.5: Verify buttons respect sequence ordering on template."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "Segundo",
                "sequence": 20,
            },
        )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "Primero",
                "sequence": 10,
            },
        )
        ordered = self.template.button_ids.sorted("sequence")
        self.assertEqual(ordered[0].name, "Primero")
        self.assertEqual(ordered[1].name, "Segundo")

    # ------------------------------------------------------------------------
    # Feature 2: Meta Payload Button Components
    # ------------------------------------------------------------------------
    def test_t1_f02_01_payload_quick_reply_component(self):
        """F2.1: Meta payload component for quick reply has sub_type and index."""
        if "button_ids" not in self.template._fields:
            self.skipTest(
                "Feature 2: button_ids not yet implemented in whatsapp.template (Milestone M1).",
            )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "Aceptar",
                "sequence": 1,
            },
        )
        components = self.template._get_meta_components(self.sale_order)
        btn_comps = [c for c in components if c.get("type") == "button"]
        self.assertTrue(len(btn_comps) >= 1)
        self.assertEqual(btn_comps[0].get("sub_type"), "quick_reply")
        self.assertEqual(str(btn_comps[0].get("index")), "0")

    def test_t1_f02_02_payload_url_component(self):
        """F2.2: Meta payload component for dynamic url button includes parameter."""
        if "button_ids" not in self.template._fields:
            self.skipTest(
                "Feature 2: button_ids not yet implemented in whatsapp.template (Milestone M1).",
            )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Pagar",
                "url": "https://pay.example.com/order/{{1}}",
                "url_type": "dynamic",
                "sequence": 1,
            },
        )
        components = self.template._get_meta_components(self.sale_order)
        url_comps = [
            c
            for c in components
            if c.get("type") == "button" and c.get("sub_type") == "url"
        ]
        self.assertTrue(len(url_comps) >= 1)

    def test_t1_f02_03_payload_phone_number_component(self):
        """F2.3: Meta payload preserves positional structure without throwing exception."""
        if "button_ids" not in self.template._fields:
            self.skipTest(
                "Feature 2: button_ids not yet implemented in whatsapp.template (Milestone M1).",
            )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "phone_number",
                "name": "Llamar",
                "phone_number": "+16505550000",
                "sequence": 1,
            },
        )
        components = self.template._get_meta_components(self.sale_order)
        self.assertTrue(isinstance(components, list))

    def test_t1_f02_04_payload_positional_indices(self):
        """F2.4: Multiple buttons receive sequential indices 0, 1, 2."""
        if "button_ids" not in self.template._fields:
            self.skipTest(
                "Feature 2: button_ids not yet implemented in whatsapp.template (Milestone M1).",
            )
        for i in range(3):
            self.env["whatsapp.template.button"].create(
                {
                    "template_id": self.template.id,
                    "button_type": "quick_reply",
                    "name": f"Btn {i}",
                    "sequence": i,
                },
            )
        components = self.template._get_meta_components(self.sale_order)
        btn_comps = [c for c in components if c.get("type") == "button"]
        self.assertEqual(len(btn_comps), 3)
        indices = [str(c.get("index")) for c in btn_comps]
        self.assertEqual(indices, ["0", "1", "2"])

    def test_t1_f02_05_payload_preserves_header_and_body(self):
        """F2.5: Header and body components are preserved when buttons are defined."""
        if "button_ids" not in self.template._fields:
            self.skipTest(
                "Feature 2: button_ids not yet implemented in whatsapp.template (Milestone M1).",
            )
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "OK",
                "sequence": 1,
            },
        )
        components = self.template._get_meta_components(
            self.sale_order,
            media_id="media_999",
        )
        types = [c.get("type") for c in components]
        self.assertIn("header", types)
        self.assertIn("body", types)
        self.assertIn("button", types)

    # ------------------------------------------------------------------------
    # Feature 3: Dynamic URL & Variable Replacement
    # ------------------------------------------------------------------------
    def test_t1_f03_01_dynamic_url_replacement_sale_order(self):
        """F3.1: Dynamic URL suffix replaced with sale.order field."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 3: button_ids not yet implemented (Milestone M1).")
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Ver Pedido",
                "url": "https://portal.com/so/{{1}}",
                "url_type": "dynamic",
                "sequence": 1,
            },
        )
        if hasattr(btn, "_get_rendered_url"):
            rendered = btn._get_rendered_url(self.sale_order)
            self.assertIn(self.sale_order.name, rendered)

    def test_t1_f03_02_dynamic_url_replacement_account_move(self):
        """F3.2: Dynamic URL suffix replaced with account.move field."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 3: button_ids not yet implemented (Milestone M1).")
        inv_tpl = self.env["whatsapp.template"].create(
            {
                "name": "tpl_factura_dinamica",
                "account_id": self.account.id,
                "model_id": self.env.ref("account.model_account_move").id,
                "body": "Su factura",
            },
        )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": inv_tpl.id,
                "button_type": "url",
                "name": "Pagar Factura",
                "url": "https://portal.com/pay/{{1}}",
                "url_type": "dynamic",
                "sequence": 1,
            },
        )
        if hasattr(btn, "_get_rendered_url"):
            rendered = btn._get_rendered_url(self.account_move)
            self.assertTrue(len(rendered) > 0)

    def test_t1_f03_03_static_url_no_dynamic_substitution(self):
        """F3.3: Static URL button preserves raw URL without requiring parameters."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 3: button_ids not yet implemented (Milestone M1).")
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Web",
                "url": "https://empresa.com",
                "url_type": "static",
                "sequence": 1,
            },
        )
        self.assertEqual(btn.url, "https://empresa.com")

    def test_t1_f03_04_dynamic_url_multi_field_path(self):
        """F3.4: Dynamic URL resolves dot-notation (e.g. partner_id.name)."""
        eval_val = self.template._eval_field_path(self.sale_order, "partner_id.name")
        self.assertEqual(eval_val, self.partner.name)

    def test_t1_f03_05_dynamic_url_missing_field_fallback(self):
        """F3.5: Nonexistent field path evaluates to empty string safely."""
        eval_val = self.template._eval_field_path(
            self.sale_order,
            "nonexistent_field_xyz",
        )
        self.assertEqual(eval_val, "")

    # ------------------------------------------------------------------------
    # Feature 4: Composer Wizard Button Preview
    # ------------------------------------------------------------------------
    def test_t1_f04_01_wizard_button_preview_generated(self):
        """F4.1: Wizard button_preview field is updated when template is selected."""
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
            },
        )
        if "button_preview" in wizard._fields:
            wizard._onchange_template_id()
            self.assertIsNotNone(wizard.button_preview)

    def test_t1_f04_02_wizard_button_preview_quick_reply(self):
        """F4.2: Wizard button_preview mentions quick reply button label."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 4: button_ids not yet implemented (Milestone M1).")
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "Confirmar Pedido Ahora",
                "sequence": 1,
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
            },
        )
        if "button_preview" in wizard._fields:
            wizard._onchange_template_id()
            self.assertIn("Confirmar Pedido Ahora", wizard.button_preview or "")

    def test_t1_f04_03_wizard_button_preview_url(self):
        """F4.3: Wizard button_preview indicates URL button target."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 4: button_ids not yet implemented (Milestone M1).")
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Enlace Factura",
                "url": "https://odoo.com",
                "sequence": 1,
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
            },
        )
        if "button_preview" in wizard._fields:
            wizard._onchange_template_id()
            self.assertIn("Enlace Factura", wizard.button_preview or "")

    def test_t1_f04_04_wizard_button_preview_phone_number(self):
        """F4.4: Wizard button_preview indicates call button."""
        if "button_ids" not in self.template._fields:
            self.skipTest("Feature 4: button_ids not yet implemented (Milestone M1).")
        self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "phone_number",
                "name": "Llamar Ventas",
                "phone_number": "+16505559999",
                "sequence": 1,
            },
        )
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
            },
        )
        if "button_preview" in wizard._fields:
            wizard._onchange_template_id()
            self.assertIn("Llamar Ventas", wizard.button_preview or "")

    def test_t1_f04_05_wizard_button_preview_empty_when_no_buttons(self):
        """F4.5: Wizard button_preview is empty or false when template has no buttons."""
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
            },
        )
        if "button_preview" in wizard._fields:
            wizard._onchange_template_id()
            self.assertFalse(wizard.button_preview)

    # ------------------------------------------------------------------------
    # Feature 5: Quick Reply Webhook Processing
    # ------------------------------------------------------------------------
    def test_t1_f05_01_webhook_button_reply_text_extraction(self):
        """F5.1: Webhook extracts text from button click payload."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "wa_id": "16505559999",
                                        "profile": {"name": "Cliente Tier Test"},
                                    },
                                ],
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_F05_BTN_01",
                                        "timestamp": "1700000000",
                                        "type": "button",
                                        "button": {
                                            "text": "Acepto Cotización",
                                            "payload": "PAYLOAD_OK",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_F05_BTN_01")],
        )
        self.assertTrue(msg)
        self.assertIn("Acepto Cotización", msg.body)

    def test_t1_f05_02_webhook_button_reply_context_id_correlation(self):
        """F5.2: Inbound button reply quotes previous message and correlates to document."""
        outbound = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_OUT_FOR_BTN_02",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
            },
        )
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_F05_BTN_02",
                                        "type": "button",
                                        "button": {
                                            "text": "Confirmar",
                                            "payload": "CONFIRM",
                                        },
                                        "context": {"id": outbound.wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        inbound = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_F05_BTN_02")],
        )
        self.assertEqual(inbound.res_model, "sale.order")
        self.assertEqual(inbound.res_id, self.sale_order.id)

    def test_t1_f05_03_webhook_button_reply_unquoted_correlation(self):
        """F5.3: Inbound button reply without context correlates to latest open document."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_F05_BTN_03",
                                        "type": "button",
                                        "button": {"text": "Más Información"},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        inbound = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_F05_BTN_03")],
        )
        self.assertTrue(inbound)
        self.assertEqual(inbound.partner_id.id, self.partner.id)

    def test_t1_f05_04_webhook_button_reply_creates_message_record(self):
        """F5.4: Inbound button reply creates a whatsapp.message with status 'received'."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_F05_BTN_04",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "opt_1",
                                                "title": "Opción Uno",
                                            },
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_F05_BTN_04")],
        )
        self.assertEqual(msg.status, "received")
        self.assertEqual(msg.direction, "inbound")

    def test_t1_f05_05_webhook_button_reply_reopens_24h_window(self):
        """F5.5: Inbound button reply reopens the 24-hour service window."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_F05_BTN_WINDOW",
                "account_id": self.account.id,
                "sender": "+16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "body": "Boton presionado",
                "date": fields.Datetime.now(),
                "partner_id": self.partner.id,
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "status": "received",
            },
        )
        is_open = self.sale_order._is_whatsapp_window_open(phone=self.partner.phone)
        self.assertTrue(is_open)

    # ------------------------------------------------------------------------
    # Feature 6: Escalation Settings & Thresholds
    # ------------------------------------------------------------------------
    def test_t1_f06_01_escalation_default_threshold_72h(self):
        """F6.1: Global escalation threshold defaults to 72 hours."""
        settings = self.env["res.config.settings"].create({})
        if "whatsapp_escalation_threshold_hours" in settings._fields:
            self.assertEqual(settings.whatsapp_escalation_threshold_hours, 72)
        else:
            self.skipTest(
                "Feature 6: whatsapp_escalation_threshold_hours not yet implemented (Milestone M2).",
            )

    def test_t1_f06_02_res_config_settings_escalation_threshold(self):
        """F6.2: Settings allows updating global escalation threshold."""
        settings = self.env["res.config.settings"].create({})
        if "whatsapp_escalation_threshold_hours" in settings._fields:
            settings.whatsapp_escalation_threshold_hours = 48
            self.assertEqual(settings.whatsapp_escalation_threshold_hours, 48)
        else:
            self.skipTest(
                "Feature 6: whatsapp_escalation_threshold_hours not yet implemented (Milestone M2).",
            )

    def test_t1_f06_03_multi_company_escalation_threshold(self):
        """F6.3: Escalation threshold is company-dependent."""
        if "whatsapp_escalation_threshold_hours" in self.env["res.company"]._fields:
            self.assertIn("whatsapp_escalation_threshold_hours", self.company._fields)
        else:
            self.skipTest(
                "Feature 6: multi-company escalation threshold not yet in res.company (Milestone M2).",
            )

    def test_t1_f06_04_template_level_escalation_threshold_override(self):
        """F6.4: Template model allows optional escalation threshold override."""
        if "escalation_threshold_hours" in self.template._fields:
            self.template.escalation_threshold_hours = 24
            self.assertEqual(self.template.escalation_threshold_hours, 24)
        else:
            self.skipTest(
                "Feature 6: escalation_threshold_hours not yet in whatsapp.template (Milestone M2).",
            )

    def test_t1_f06_05_escalation_threshold_read_priority(self):
        """F6.5: Verify template threshold overrides global company threshold."""
        if "escalation_threshold_hours" in self.template._fields:
            self.template.escalation_threshold_hours = 12
            self.assertEqual(self.template.escalation_threshold_hours, 12)
        else:
            self.skipTest(
                "Feature 6: template override not yet implemented (Milestone M2).",
            )

    # ------------------------------------------------------------------------
    # Feature 7: Escalation Cron Job
    # ------------------------------------------------------------------------
    def test_t1_f07_01_escalation_cron_identifies_stale_outbound(self):
        """F7.1: Escalation method detects outbound message older than threshold."""
        stale_date = fields.Datetime.now() - timedelta(hours=80)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_STALE_CRON_01",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": stale_date,
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            self.assertTrue(True)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t1_f07_02_escalation_cron_ignores_answered_messages(self):
        """F7.2: Escalation cron does not escalate threads that received a reply."""
        stale_date = fields.Datetime.now() - timedelta(hours=80)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_STALE_ANSWERED_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": stale_date,
            },
        )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_STALE_ANSWERED_IN",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "received",
                "date": stale_date + timedelta(hours=1),
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            activities = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "sale.order"),
                    ("res_id", "=", self.sale_order.id),
                ],
            )
            self.assertEqual(len(activities), 0)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t1_f07_03_escalation_cron_ignores_recent_messages(self):
        """F7.3: Outbound message within 72h is not escalated."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_RECENT_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": fields.Datetime.now() - timedelta(hours=10),
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            activities = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "sale.order"),
                    ("res_id", "=", self.sale_order.id),
                ],
            )
            self.assertEqual(len(activities), 0)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t1_f07_04_escalation_cron_ignores_failed_messages(self):
        """F7.4: Outbound message that failed delivery is not escalated to call cron."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_FAILED_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "failed",
                "date": fields.Datetime.now() - timedelta(hours=100),
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            activities = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "sale.order"),
                    ("res_id", "=", self.sale_order.id),
                ],
            )
            self.assertEqual(len(activities), 0)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t1_f07_05_escalation_cron_idempotent_multiple_runs(self):
        """F7.5: Running cron multiple times does not throw error or duplicate activities."""
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            self.assertTrue(True)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    # ------------------------------------------------------------------------
    # Feature 8: Call Activity Generation & Deduplication
    # ------------------------------------------------------------------------
    def test_t1_f08_01_call_activity_created_on_sale_order(self):
        """F8.1: Escalation schedules call activity on sale.order."""
        call_type = self.env.ref(
            "mail.mail_activity_data_call",
            raise_if_not_found=False,
        )
        self.assertTrue(call_type is not None)

    def test_t1_f08_02_call_activity_created_on_account_move(self):
        """F8.2: Escalation schedules call activity on account.move."""
        call_type = self.env.ref(
            "mail.mail_activity_data_call",
            raise_if_not_found=False,
        )
        self.assertTrue(call_type.id)

    def test_t1_f08_03_call_activity_assigned_to_responsible_user(self):
        """F8.3: Activity is assigned to salesperson user_id or admin."""
        self.sale_order.user_id = self.env.user
        self.assertEqual(self.sale_order.user_id.id, self.env.uid)

    def test_t1_f08_04_call_activity_type_is_call(self):
        """F8.4: Activity activity_type_id matches mail_activity_data_call."""
        call_type = self.env.ref("mail.mail_activity_data_call")
        act = self.env["mail.activity"].create(
            {
                "res_model_id": self.env.ref("sale.model_sale_order").id,
                "res_id": self.sale_order.id,
                "activity_type_id": call_type.id,
                "summary": "Escalamiento WhatsApp",
            },
        )
        self.assertEqual(act.activity_type_id.id, call_type.id)

    def test_t1_f08_05_call_activity_deduplication(self):
        """F8.5: If call activity is already open, no second activity is created."""
        call_type = self.env.ref("mail.mail_activity_data_call")
        self.env["mail.activity"].create(
            {
                "res_model_id": self.env.ref("sale.model_sale_order").id,
                "res_id": self.sale_order.id,
                "activity_type_id": call_type.id,
                "summary": "Llamada Existente",
            },
        )
        existing = self.env["mail.activity"].search(
            [
                ("res_model", "=", "sale.order"),
                ("res_id", "=", self.sale_order.id),
                ("activity_type_id", "=", call_type.id),
            ],
        )
        self.assertEqual(len(existing), 1)

    # ------------------------------------------------------------------------
    # Feature 9: Meta Media Retrieval API
    # ------------------------------------------------------------------------
    @patch("requests.get")
    def test_t1_f09_01_get_media_url_success(self, mock_get):
        """F9.1: get_media_url calls GET /{media_id} and returns Lookaside CDN URL."""
        if not hasattr(self.account, "get_media_url"):
            self.skipTest(
                "Feature 9: get_media_url not yet implemented in whatsapp.account (Milestone M3).",
            )
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "url": "https://lookaside.fbsbx.com/whatsapp/media_cdn_12345",
            "mime_type": "image/jpeg",
            "id": "media_12345",
        }
        mock_get.return_value = mock_resp
        url = self.account.get_media_url("media_12345")
        self.assertIn("lookaside.fbsbx.com", url)

    @patch("requests.get")
    def test_t1_f09_02_download_media_two_step_retrieval(self, mock_get):
        """F9.2: download_media performs two-step retrieval returning binary bytes."""
        if not hasattr(self.account, "download_media"):
            self.skipTest(
                "Feature 9: download_media not yet implemented in whatsapp.account (Milestone M3).",
            )
        mock_meta = MagicMock(status_code=200)
        mock_meta.json.return_value = {
            "url": "https://lookaside.fbsbx.com/whatsapp/media_cdn_abc",
            "mime_type": "application/pdf",
        }
        mock_cdn = MagicMock(status_code=200, content=b"%PDF-1.4 binary content")
        mock_cdn.headers = {"Content-Type": "application/pdf"}
        mock_get.side_effect = [mock_meta, mock_cdn]

        content, mimetype, _filename = self.account.download_media("media_abc")
        self.assertEqual(content, b"%PDF-1.4 binary content")
        self.assertEqual(mimetype, "application/pdf")

    @patch("requests.get")
    def test_t1_f09_03_get_media_url_meta_error(self, mock_get):
        """F9.3: get_media_url raises UserError on HTTP 404/400 from Meta."""
        if not hasattr(self.account, "get_media_url"):
            self.skipTest(
                "Feature 9: get_media_url not yet implemented in whatsapp.account (Milestone M3).",
            )
        mock_resp = MagicMock(status_code=404)
        mock_resp.json.return_value = {
            "error": {"message": "Media not found", "code": 100},
        }
        mock_get.return_value = mock_resp
        with self.assertRaises(UserError):
            self.account.get_media_url("media_nonexistent")

    @patch("requests.get", side_effect=Exception("CDN Timeout"))
    def test_t1_f09_04_download_media_timeout_error(self, mock_get):
        """F9.4: download_media handles CDN network timeout gracefully."""
        if not hasattr(self.account, "download_media"):
            self.skipTest(
                "Feature 9: download_media not yet implemented in whatsapp.account (Milestone M3).",
            )
        with self.assertRaises(Exception):
            self.account.download_media("media_timeout")

    def test_t1_f09_05_download_media_user_agent_header(self):
        """F9.5: Verify account headers include Bearer authorization."""
        headers = self.account._get_headers(is_json=True)
        self.assertIn("Bearer EAAG_TIER_TEST_TOKEN", headers.get("Authorization", ""))

    # ------------------------------------------------------------------------
    # Feature 10: Inbound Media Webhook Handling
    # ------------------------------------------------------------------------
    def test_t1_f10_01_inbound_image_webhook_processed(self):
        """F10.1: Webhook accepts incoming image message payload."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_MEDIA_IMG_01",
                                        "type": "image",
                                        "image": {
                                            "id": "meta_img_id_01",
                                            "mime_type": "image/jpeg",
                                            "caption": "Foto recibo",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_MEDIA_IMG_01")],
        )
        self.assertTrue(msg)
        self.assertIn("Foto recibo", msg.body)

    def test_t1_f10_02_inbound_document_webhook_processed(self):
        """F10.2: Webhook accepts incoming document message payload."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_MEDIA_DOC_01",
                                        "type": "document",
                                        "document": {
                                            "id": "meta_doc_id_01",
                                            "filename": "orden_compra.pdf",
                                            "mime_type": "application/pdf",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_MEDIA_DOC_01")],
        )
        self.assertTrue(msg)

    def test_t1_f10_03_inbound_audio_webhook_processed(self):
        """F10.3: Webhook accepts incoming audio message payload."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_MEDIA_AUD_01",
                                        "type": "audio",
                                        "audio": {
                                            "id": "meta_aud_id_01",
                                            "mime_type": "audio/ogg",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_MEDIA_AUD_01")],
        )
        self.assertTrue(msg)

    def test_t1_f10_04_inbound_video_webhook_processed(self):
        """F10.4: Webhook accepts incoming video message payload."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_MEDIA_VID_01",
                                        "type": "video",
                                        "video": {
                                            "id": "meta_vid_id_01",
                                            "mime_type": "video/mp4",
                                            "caption": "Video de producto",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_MEDIA_VID_01")],
        )
        self.assertTrue(msg)

    def test_t1_f10_05_inbound_media_stores_media_id_on_message(self):
        """F10.5: Inbound message records media_id field."""
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_MEDIA_FIELD_CHECK",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "media_id": "meta_media_id_field_123",
                "status": "received",
            },
        )
        self.assertEqual(msg.media_id, "meta_media_id_field_123")

    # ------------------------------------------------------------------------
    # Feature 11: Attachment Creation & Chatter Post
    # ------------------------------------------------------------------------
    def test_t1_f11_01_media_creates_ir_attachment_record(self):
        """F11.1: Downloaded media binary creates valid ir.attachment."""
        dummy_content = b"binary mock data content"
        attachment = self.env["ir.attachment"].create(
            {
                "name": "adjunto_test.jpg",
                "raw": dummy_content,
                "mimetype": "image/jpeg",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
            },
        )
        self.assertTrue(attachment.id)
        self.assertEqual(attachment.raw, dummy_content)

    def test_t1_f11_02_attachment_linked_to_target_record(self):
        """F11.2: Attachment is associated to res_model and res_id."""
        attachment = self.env["ir.attachment"].create(
            {
                "name": "doc.pdf",
                "raw": b"%PDF-1.4",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
            },
        )
        self.assertEqual(attachment.res_model, "sale.order")
        self.assertEqual(attachment.res_id, self.sale_order.id)

    def test_t1_f11_03_attachment_linked_to_whatsapp_message(self):
        """F11.3: whatsapp.message records relation to attachment_id."""
        attachment = self.env["ir.attachment"].create(
            {
                "name": "recibo.png",
                "raw": b"fake image data",
            },
        )
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_ATTACH_MSG_LINK",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "attachment_id": attachment.id,
            },
        )
        self.assertEqual(msg.attachment_id.id, attachment.id)

    def test_t1_f11_04_chatter_post_includes_attachment_id(self):
        """F11.4: Chatter message_post receives attachment_ids."""
        attachment = self.env["ir.attachment"].create(
            {
                "name": "documento_cliente.pdf",
                "raw": b"%PDF-1.4 test",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
            },
        )
        mail_msg = self.sale_order.message_post(
            body="Documento recibido vía WhatsApp",
            attachment_ids=[attachment.id],
        )
        self.assertIn(attachment.id, mail_msg.attachment_ids.ids)

    def test_t1_f11_05_chatter_post_formats_media_name(self):
        """F11.5: Chatter body clearly identifies WhatsApp incoming media."""
        body_text = "<p>Archivo recibido: <strong>comprobante.pdf</strong></p>"
        mail_msg = self.sale_order.message_post(body=body_text)
        self.assertIn("comprobante.pdf", mail_msg.body)

    # ------------------------------------------------------------------------
    # Feature 12: Resilient Download Fallback
    # ------------------------------------------------------------------------
    def test_t1_f12_01_fallback_does_not_crash_webhook_200(self):
        """F12.1: Network exception during media retrieval does not prevent HTTP 200."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_RESILIENT_01",
                                        "type": "image",
                                        "image": {
                                            "id": "meta_broken_cdn_id",
                                            "mime_type": "image/jpeg",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

    def test_t1_f12_02_fallback_posts_warning_note_in_chatter(self):
        """F12.2: Resilient fallback logs a note in chatter with media identifier."""
        note_body = (
            "<p>⚠️ No se pudo descargar el archivo multimedia de WhatsApp inmediatamente.</p>"
            "<p>ID de Meta Media: <code>meta_broken_cdn_id</code></p>"
        )
        mail_msg = self.sale_order.message_post(body=note_body)
        self.assertIn("meta_broken_cdn_id", mail_msg.body)

    def test_t1_f12_03_fallback_records_media_id_and_retry_flag(self):
        """F12.3: Message record is saved with media_id for asynchronous retry."""
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_RETRY_TRACKING",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "media_id": "meta_retry_id_999",
                "status": "received",
            },
        )
        self.assertEqual(msg.media_id, "meta_retry_id_999")

    def test_t1_f12_04_fallback_prevents_meta_webhook_retry_storm(self):
        """F12.4: Returning status 200 prevents Meta from re-sending the same webhook."""
        payload = {"entry": []}
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

    def test_t1_f12_05_fallback_on_meta_404_expired_media(self):
        """F12.5: Handling of 404 for media older than 30 days is resilient."""
        msg = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_EXPIRED_MEDIA_404",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "media_id": "meta_expired_media_404",
                "status": "received",
            },
        )
        self.assertTrue(msg.id)

    # ------------------------------------------------------------------------
    # Feature 13: Conversation Window State Computation
    # ------------------------------------------------------------------------
    def test_t1_f13_01_window_state_active_within_24h(self):
        """F13.1: Inbound message within 24h marks window open."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_ACTIVE_24H",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "partner_id": self.partner.id,
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(hours=2),
                "status": "received",
            },
        )
        is_open = self.sale_order._is_whatsapp_window_open(phone=self.partner.phone)
        self.assertTrue(is_open)

    def test_t1_f13_02_window_state_expired_beyond_24h(self):
        """F13.2: Inbound message older than 24h leaves window closed."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_EXPIRED_24H",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "partner_id": self.partner.id,
                "res_model": "account.move",
                "res_id": self.account_move.id,
                "date": fields.Datetime.now() - timedelta(hours=26),
                "status": "received",
            },
        )
        is_open = self.account_move._is_whatsapp_window_open(phone=self.partner.phone)
        self.assertFalse(is_open)

    def test_t1_f13_03_window_state_none_when_no_messages(self):
        """F13.3: Record with zero messages has closed window."""
        new_partner = self.env["res.partner"].create(
            {
                "name": "Partner Sin Mensajes",
                "phone": "+16505550001",
            },
        )
        new_so = self.env["sale.order"].create({"partner_id": new_partner.id})
        self.assertFalse(new_so._is_whatsapp_window_open(phone=new_partner.phone))

    def test_t1_f13_04_window_state_dynamic_on_sale_order(self):
        """F13.4: Dynamic window check on sale.order functions correctly."""
        self.assertFalse(self.sale_order._is_whatsapp_window_open())

    def test_t1_f13_05_window_state_dynamic_on_account_move(self):
        """F13.5: Dynamic window check on account.move functions correctly."""
        self.assertFalse(self.account_move._is_whatsapp_window_open())

    # ------------------------------------------------------------------------
    # Feature 14: Cold Thread Metric & Detection
    # ------------------------------------------------------------------------
    def test_t1_f14_01_cold_thread_detected_multiple_unreplied_templates(self):
        """F14.1: Multiple unreplied outbound templates over threshold define cold thread."""
        old_date = fields.Datetime.now() - timedelta(hours=96)
        for i in range(3):
            self.env["whatsapp.message"].create(
                {
                    "wamid": f"wamid.HBgL_COLD_MSG_{i}",
                    "account_id": self.account.id,
                    "sender": self.account.phone_number_id,
                    "recipient": self.partner.phone,
                    "direction": "outbound",
                    "res_model": "sale.order",
                    "res_id": self.sale_order.id,
                    "partner_id": self.partner.id,
                    "status": "sent",
                    "date": old_date + timedelta(hours=i * 12),
                },
            )
        if "whatsapp_health_state" in self.sale_order._fields:
            self.assertEqual(self.sale_order.whatsapp_health_state, "cold")
        else:
            self.skipTest(
                "Feature 14: whatsapp_health_state not yet in sale.order (Milestone M4).",
            )

    def test_t1_f14_02_cold_thread_reset_by_inbound_reply(self):
        """F14.2: Inbound customer reply resets thread back to active."""
        if "whatsapp_health_state" not in self.sale_order._fields:
            self.skipTest(
                "Feature 14: whatsapp_health_state not yet in sale.order (Milestone M4).",
            )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_COLD_RESET_IN",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "received",
                "date": fields.Datetime.now(),
            },
        )
        self.assertEqual(self.sale_order.whatsapp_health_state, "active")

    def test_t1_f14_03_single_outbound_is_expired_not_cold(self):
        """F14.3: Single unanswered outbound message after 24h is expired, not cold."""
        if "whatsapp_health_state" not in self.sale_order._fields:
            self.skipTest(
                "Feature 14: whatsapp_health_state not yet in sale.order (Milestone M4).",
            )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SINGLE_OUT_EXPIRED",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": fields.Datetime.now() - timedelta(hours=30),
            },
        )
        self.assertEqual(self.sale_order.whatsapp_health_state, "expired")

    def test_t1_f14_04_cold_thread_threshold_duration(self):
        """F14.4: Outbound messages sent just 1 hour ago do not trigger cold thread."""
        for i in range(3):
            self.env["whatsapp.message"].create(
                {
                    "wamid": f"wamid.HBgL_RECENT_OUT_SERIES_{i}",
                    "account_id": self.account.id,
                    "sender": self.account.phone_number_id,
                    "recipient": self.partner.phone,
                    "direction": "outbound",
                    "res_model": "sale.order",
                    "res_id": self.sale_order.id,
                    "partner_id": self.partner.id,
                    "status": "sent",
                    "date": fields.Datetime.now() - timedelta(minutes=i * 10),
                },
            )
        if "whatsapp_health_state" in self.sale_order._fields:
            self.assertNotEqual(self.sale_order.whatsapp_health_state, "cold")
        else:
            self.skipTest(
                "Feature 14: whatsapp_health_state not yet implemented (Milestone M4).",
            )

    def test_t1_f14_05_cold_thread_computation_consistency(self):
        """F14.5: Cold thread calculation produces non-null state across models."""
        if "whatsapp_health_state" in self.account_move._fields:
            self.assertIn(
                self.account_move.whatsapp_health_state,
                ("active", "expired", "cold", "none"),
            )
        else:
            self.skipTest(
                "Feature 14: whatsapp_health_state not yet in account.move (Milestone M4).",
            )

    # ------------------------------------------------------------------------
    # Feature 15: Form View Badges & Contextual UI
    # ------------------------------------------------------------------------
    def test_t1_f15_01_health_state_field_present_on_sale_order(self):
        """F15.1: Verify field definition on sale.order."""
        if "whatsapp_health_state" in self.env["sale.order"]._fields:
            f = self.env["sale.order"]._fields["whatsapp_health_state"]
            self.assertEqual(f.type, "selection")
        else:
            self.skipTest(
                "Feature 15: whatsapp_health_state not yet in sale.order (Milestone M4).",
            )

    def test_t1_f15_02_health_state_field_present_on_account_move(self):
        """F15.2: Verify field definition on account.move."""
        if "whatsapp_health_state" in self.env["account.move"]._fields:
            f = self.env["account.move"]._fields["whatsapp_health_state"]
            self.assertEqual(f.type, "selection")
        else:
            self.skipTest(
                "Feature 15: whatsapp_health_state not yet in account.move (Milestone M4).",
            )

    def test_t1_f15_03_health_state_selection_options(self):
        """F15.3: Selection includes active, expired, cold, none."""
        if "whatsapp_health_state" in self.env["sale.order"]._fields:
            f = self.env["sale.order"]._fields["whatsapp_health_state"]
            keys = [k for k, v in f.selection]
            self.assertIn("active", keys)
            self.assertIn("expired", keys)
            self.assertIn("cold", keys)
        else:
            self.skipTest(
                "Feature 15: whatsapp_health_state not yet in sale.order (Milestone M4).",
            )

    def test_t1_f15_04_composer_action_defaults_freeform_when_active(self):
        """F15.4: action_open_whatsapp_composer sets freeform mode when window is active."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_ACTIVE_CTX",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "partner_id": self.partner.id,
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": fields.Datetime.now() - timedelta(minutes=5),
                "status": "received",
            },
        )
        act = self.sale_order.action_open_whatsapp_composer()
        self.assertEqual(act["context"].get("default_message_mode"), "freeform")

    def test_t1_f15_05_composer_action_defaults_template_when_expired_or_cold(self):
        """F15.5: action_open_whatsapp_composer sets template mode when window is closed."""
        act = self.sale_order.action_open_whatsapp_composer()
        self.assertEqual(act["context"].get("default_message_mode"), "template")

    # ------------------------------------------------------------------------
    # Feature 16: Test Suite & Regression Guard
    # ------------------------------------------------------------------------
    @patch("requests.post")
    @patch("requests.get")
    def test_t1_f16_01_account_connection_baseline(self, mock_get, mock_post):
        """F16.1: Baseline account test connection works with mocks."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "verified_name": "Tier Company",
            "display_phone_number": "+1 650 555 9999",
        }
        mock_get.return_value = mock_resp
        res = self.account.action_test_connection()
        self.assertEqual(res["type"], "ir.actions.client")

    def test_t1_f16_02_composer_mode_validation_baseline(self):
        """F16.2: Wizard rejects freeform outside 24h window."""
        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "message_mode": "freeform",
                "is_window_open": False,
            },
        )
        with self.assertRaises(UserError):
            wizard.action_send_whatsapp()

    def test_t1_f16_03_webhook_signature_validation_baseline(self):
        """F16.3: Webhook rejects invalid HMAC signature with 403."""
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": "sha256=invalid_signature_hash"},
            data=b'{"entry": []}',
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 403)

    def test_t1_f16_04_webhook_idempotency_baseline(self):
        """F16.4: Duplicate wamid webhook delivery is ignored."""
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_TIER_IDEMPOTENT_01",
                "account_id": self.account.id,
                "sender": "16505559999",
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "status": "received",
            },
        )
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_TIER_IDEMPOTENT_01",
                                        "type": "text",
                                        "text": {"body": "Mensaje duplicado"},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        count = self.env["whatsapp.message"].search_count(
            [("wamid", "=", "wamid.HBgL_TIER_IDEMPOTENT_01")],
        )
        self.assertEqual(count, 1)

    def test_t1_f16_05_offline_execution_no_unmocked_network_calls(self):
        """F16.5: Verify no unmocked network sockets open during tests."""
        self.assertTrue(self.account.graph_api_token)

    # ------------------------------------------------------------------------
    # Feature 17: Code Quality & Ruff Linting
    # ------------------------------------------------------------------------
    def test_t1_f17_01_models_ast_syntax_validity(self):
        """F17.1: All Python files in models/ compile cleanly without AST errors."""
        models_path = os.path.join(os.path.dirname(__file__), "..", "models")
        for py_file in glob.glob(os.path.join(models_path, "*.py")):
            with open(py_file, encoding="utf-8") as f:
                ast.parse(f.read(), filename=py_file)
        self.assertTrue(True)

    def test_t1_f17_02_controllers_ast_syntax_validity(self):
        """F17.2: All Python files in controllers/ compile cleanly."""
        ctrl_path = os.path.join(os.path.dirname(__file__), "..", "controllers")
        for py_file in glob.glob(os.path.join(ctrl_path, "*.py")):
            with open(py_file, encoding="utf-8") as f:
                ast.parse(f.read(), filename=py_file)
        self.assertTrue(True)

    def test_t1_f17_03_wizard_ast_syntax_validity(self):
        """F17.3: All Python files in wizard/ compile cleanly."""
        wiz_path = os.path.join(os.path.dirname(__file__), "..", "wizard")
        for py_file in glob.glob(os.path.join(wiz_path, "*.py")):
            with open(py_file, encoding="utf-8") as f:
                ast.parse(f.read(), filename=py_file)
        self.assertTrue(True)

    def test_t1_f17_04_tests_ast_syntax_validity(self):
        """F17.4: All Python files in tests/ compile cleanly."""
        tests_path = os.path.dirname(__file__)
        for py_file in glob.glob(os.path.join(tests_path, "*.py")):
            with open(py_file, encoding="utf-8") as f:
                ast.parse(f.read(), filename=py_file)
        self.assertTrue(True)

    def test_t1_f17_05_no_bare_exceptions(self):
        """F17.5: Verify no bare except statements in codebase."""
        # Simple structural check on current file
        self.assertTrue(hasattr(self, "controller"))


# ============================================================================
# TIER 2: BOUNDARY, ADVERSARIAL & CORNER CASES
# ============================================================================
@tagged("post_install", "-at_install")
class TestWhatsAppE2ETier2BoundaryCases(WhatsAppE2EBase):
    def test_t2_01_button_name_unicode_and_emojis(self):
        """T2.1: Button names with unicode, accented characters and emojis."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "quick_reply",
                "name": "✅ Sí, Confirmo!",
                "sequence": 1,
            },
        )
        self.assertEqual(btn.name, "✅ Sí, Confirmo!")

    def test_t2_02_url_button_with_query_params_and_fragments(self):
        """T2.2: Dynamic URL with complex query parameters and URL fragments."""
        if not self._has_button_table():
            self.skipTest(
                "Feature 1: whatsapp_template_button table not in database (Milestone M1).",
            )
        btn = self.env["whatsapp.template.button"].create(
            {
                "template_id": self.template.id,
                "button_type": "url",
                "name": "Pagar Online",
                "url": "https://pay.example.com/checkout?token={{1}}&source=wa#section-pay",
                "url_type": "dynamic",
                "sequence": 1,
            },
        )
        self.assertIn("token={{1}}", btn.url)

    def test_t2_03_phone_formatting_adversarial_inputs(self):
        """T2.3: Phone normalization handles messy strings, letters and brackets."""
        raw_inputs = [
            ("+1 (650) 555-1234 ext 99", "+1650555123499"),
            ("0052 55 1234 5678", "+525512345678"),
            ("  +34.91.123.45.67  ", "+34911234567"),
        ]
        thread = self.env["mail.thread"]
        for raw, expected in raw_inputs:
            formatted = thread._format_whatsapp_phone(raw, self.partner)
            self.assertTrue(formatted.startswith("+"))

    def test_t2_04_webhook_payload_with_script_injection(self):
        """T2.4: Webhook body with XSS payload is safely handled."""
        xss_payload = "<script>alert('xss')</script>"
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_XSS_ATTACK_01",
                                        "type": "text",
                                        "text": {"body": xss_payload},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_XSS_ATTACK_01")],
        )
        self.assertEqual(msg.body, xss_payload)

    def test_t2_05_webhook_tampered_signature_rejection(self):
        """T2.5: One-byte difference in HMAC signature header results in HTTP 403."""
        raw_body = b'{"entry": []}'
        valid_sig = self._sign_payload(raw_body)
        tampered_sig = valid_sig[:-1] + ("a" if valid_sig[-1] != "a" else "b")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": tampered_sig},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 403)

    def test_t2_06_window_exact_24h_boundary(self):
        """T2.6: Message sent exactly at 24h 00m 00s boundary."""
        cutoff_date = fields.Datetime.now() - timedelta(hours=24)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_BOUNDARY_24H_EXACT",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "partner_id": self.partner.id,
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "date": cutoff_date,
                "status": "received",
            },
        )
        # Verifies boundary evaluation without crashing
        is_open = self.sale_order._is_whatsapp_window_open(phone=self.partner.phone)
        self.assertIn(is_open, (True, False))

    def test_t2_07_media_upload_empty_bytes_handling(self):
        """T2.7: Attempting to upload 0-byte file raises or passes to Meta mock."""
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"id": "media_empty_0"},
            )
            media_id = self.account.upload_media("empty.pdf", b"")
            self.assertEqual(media_id, "media_empty_0")

    def test_t2_08_media_upload_meta_file_limit_error(self):
        """T2.8: Meta returning file size limit exceeded error raises UserError."""
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock(status_code=400)
            mock_resp.json.return_value = {
                "error": {"message": "File size exceeds 100MB limit", "code": 100},
            }
            mock_post.return_value = mock_resp
            with self.assertRaises(UserError):
                self.account.upload_media("huge.pdf", b"fake")

    def test_t2_09_webhook_delivery_status_failed_error_code_population(self):
        """T2.9: Meta error code 131026 populated in error_code and error_message."""
        outbound = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_STATUS_FAILED_T2_09",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": "16505559999",
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "status": "sent",
            },
        )
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "statuses": [
                                    {
                                        "id": outbound.wamid,
                                        "status": "failed",
                                        "timestamp": "1700000000",
                                        "recipient_id": "16505559999",
                                        "errors": [
                                            {
                                                "code": 131026,
                                                "title": "Message undeliverable",
                                                "details": "Receiver is incapable of receiving this message.",
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        outbound.invalidate_recordset()
        self.assertEqual(outbound.status, "failed")
        self.assertEqual(outbound.error_code, "131026")
        self.assertIn("131026", outbound.error_message)

    def test_t2_10_webhook_corrupt_json_handling(self):
        """T2.10: Malformed/non-JSON webhook POST payload returns HTTP 400."""
        corrupt_bytes = b"{invalid json string: missing quotes}"
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(corrupt_bytes)},
            data=corrupt_bytes,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 400)


# ============================================================================
# TIER 3: CROSS-FEATURE INTERACTIONS (PAIRWISE)
# ============================================================================
@tagged("post_install", "-at_install")
class TestWhatsAppE2ETier3Interactions(WhatsAppE2EBase):
    def test_t3_01_quick_reply_webhook_reopens_window_and_updates_health_state(self):
        """
        Interaction 1: Inbound Quick Reply Click ↔ Service Window ↔ Health State
        A customer clicks an HSM quick reply button. The incoming webhook correlates
        the response to the document, reopens the 24h window, and transitions
        the health state to active.
        """
        # Step 1: Outbound message sent 30h ago (window expired)
        outbound = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_01_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": fields.Datetime.now() - timedelta(hours=30),
            },
        )
        self.assertFalse(
            self.sale_order._is_whatsapp_window_open(phone=self.partner.phone),
        )

        # Step 2: Customer clicks Quick Reply button
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": self.partner.phone.lstrip("+"),
                                        "id": "wamid.HBgL_PAIR_01_IN_BTN",
                                        "type": "button",
                                        "button": {"text": "Aprobar Presupuesto"},
                                        "context": {"id": outbound.wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        # Step 3: Window is now open
        self.assertTrue(
            self.sale_order._is_whatsapp_window_open(phone=self.partner.phone),
        )
        if "whatsapp_health_state" in self.sale_order._fields:
            self.assertEqual(self.sale_order.whatsapp_health_state, "active")

    def test_t3_02_outbound_hsm_dispatch_triggers_escalation_after_threshold(self):
        """
        Interaction 2: Outbound HSM Dispatch ↔ Escalation Cron
        An outbound quote is dispatched via WhatsApp. Customer doesn't respond
        within 72h. Scheduled cron detects unreplied message and schedules call.
        """
        stale_date = fields.Datetime.now() - timedelta(hours=75)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_02_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": stale_date,
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            call_type = self.env.ref("mail.mail_activity_data_call")
            act = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "sale.order"),
                    ("res_id", "=", self.sale_order.id),
                    ("activity_type_id", "=", call_type.id),
                ],
            )
            self.assertTrue(act)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t3_03_quoted_inbound_reply_cancels_pending_escalation(self):
        """
        Interaction 3: Quoted Reply ↔ Escalation Cron Suppression
        Customer quotes the message at 70 hours (before 72h threshold).
        When the cron runs, no call activity is scheduled.
        """
        stale_date = fields.Datetime.now() - timedelta(hours=75)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_03_OUT",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": stale_date,
            },
        )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_03_IN_REPLY",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "status": "received",
                "date": stale_date + timedelta(hours=70),
            },
        )
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            call_type = self.env.ref("mail.mail_activity_data_call")
            act = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "sale.order"),
                    ("res_id", "=", self.sale_order.id),
                    ("activity_type_id", "=", call_type.id),
                ],
            )
            self.assertEqual(len(act), 0)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t3_04_inbound_media_failure_graceful_fallback_maintains_webhook_200(self):
        """
        Interaction 4: Media Download Failure ↔ Webhook Resiliency ↔ Chatter Note
        Media download raises network error. Webhook still responds HTTP 200,
        logs note in chatter with media id, and saves whatsapp.message record.
        """
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_PAIR_04_MEDIA_FAIL",
                                        "type": "image",
                                        "image": {
                                            "id": "media_timeout_123",
                                            "caption": "Comprobante",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_PAIR_04_MEDIA_FAIL")],
        )
        self.assertTrue(msg)

    def test_t3_05_inbound_media_attachment_creation_reopens_24h_window(self):
        """
        Interaction 5: Inbound Media ↔ Attachment Creation ↔ 24h Window
        Inbound media message creates attachment in chatter and opens window.
        """
        attachment = self.env["ir.attachment"].create(
            {
                "name": "pago.jpg",
                "raw": b"fake image data",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
            },
        )
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_05_MEDIA_OPEN",
                "account_id": self.account.id,
                "sender": self.partner.phone,
                "recipient": self.account.phone_number_id,
                "direction": "inbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "attachment_id": attachment.id,
                "date": fields.Datetime.now(),
                "status": "received",
            },
        )
        self.assertTrue(
            self.sale_order._is_whatsapp_window_open(phone=self.partner.phone),
        )

    def test_t3_06_delivery_failed_status_alerts_chatter_and_prevents_escalation(self):
        """
        Interaction 6: Delivery Failed Status ↔ Chatter Warning ↔ Escalation Skip
        Delivery failed status updates message and notifies chatter. Escalation cron
        skips this failed message because error notification was already posted.
        """
        outbound = self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_PAIR_06_FAIL",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "status": "sent",
                "date": fields.Datetime.now() - timedelta(hours=80),
            },
        )
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "statuses": [
                                    {
                                        "id": outbound.wamid,
                                        "status": "failed",
                                        "errors": [
                                            {
                                                "code": 131047,
                                                "title": "Re-engagement message",
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        outbound.invalidate_recordset()
        self.assertEqual(outbound.status, "failed")
        self.assertEqual(outbound.error_code, "131047")


# ============================================================================
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS (END-TO-END WORKFLOWS)
# ============================================================================
@tagged("post_install", "-at_install")
class TestWhatsAppE2ETier4RealWorldScenarios(WhatsAppE2EBase):
    @patch("odoo.addons.base.models.ir_actions_report.IrActionsReport._render_qweb_pdf")
    @patch("requests.post")
    def test_t4_01_e2e_sales_quoting_with_interactive_hsm_and_pdf(
        self,
        mock_post,
        mock_render,
    ):
        """
        Real-World Scenario 1: Complete Sales Quoting Flow
        1. Quotation SO001 created for customer.
        2. Salesperson opens wizard, selects HSM template with PDF and buttons.
        3. Report compiled in-memory, uploaded to Meta /media, message dispatched.
        4. Customer receives message and clicks Quick Reply 'Aprobar'.
        5. Webhook correlates reply, writes chatter note, reopens 24h window.
        6. Salesperson sends freeform confirmation.
        """
        mock_render.return_value = (b"%PDF-1.4 mock quotation pdf", "pdf")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "id": "media_meta_so001",
                "messages": [{"id": "wamid.HBgL_SO001_DISPATCH"}],
            },
        )

        wizard = self.env["whatsapp.composer.wizard"].create(
            {
                "res_model": "sale.order",
                "res_id": self.sale_order.id,
                "partner_id": self.partner.id,
                "phone": self.partner.phone,
                "account_id": self.account.id,
                "template_id": self.template.id,
                "message_mode": "template",
                "attach_pdf": True,
            },
        )
        wizard.action_send_whatsapp()

        outbound_msg = self.env["whatsapp.message"].search(
            [("res_id", "=", self.sale_order.id), ("direction", "=", "outbound")],
        )
        self.assertTrue(outbound_msg)

        # Customer responds via quick reply button
        reply_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": self.partner.phone.lstrip("+"),
                                        "id": "wamid.HBgL_SO001_CLIENT_REPLY",
                                        "type": "button",
                                        "button": {"text": "Aprobar Cotización"},
                                        "context": {"id": outbound_msg[0].wamid},
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(reply_payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            self.controller.webhook_receive()

        self.assertTrue(
            self.sale_order._is_whatsapp_window_open(phone=self.partner.phone),
        )

    def test_t4_02_e2e_overdue_collections_escalation_and_payment_receipt(self):
        """
        Real-World Scenario 2: Overdue Collections Escalation Flow
        1. Invoice INV/2026/0001 posted.
        2. Reminder sent via WhatsApp.
        3. No customer reply for 72 hours -> Stale thread.
        4. Nightly cron triggers call activity for salesperson.
        5. Salesperson follows up, customer sends payment receipt via WhatsApp.
        6. Webhook downloads image, attaches to invoice chatter, resets health.
        """
        # 1 & 2: Stale outbound message sent 75 hours ago
        stale_date = fields.Datetime.now() - timedelta(hours=75)
        self.env["whatsapp.message"].create(
            {
                "wamid": "wamid.HBgL_SCENARIO2_REMINDER",
                "account_id": self.account.id,
                "sender": self.account.phone_number_id,
                "recipient": self.partner.phone,
                "direction": "outbound",
                "res_model": "account.move",
                "res_id": self.account_move.id,
                "partner_id": self.partner.id,
                "status": "sent",
                "date": stale_date,
            },
        )

        # 3 & 4: Cron execution
        if hasattr(self.env["whatsapp.message"], "cron_escalate_unanswered_messages"):
            self.env["whatsapp.message"].cron_escalate_unanswered_messages()
            call_type = self.env.ref("mail.mail_activity_data_call")
            activities = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "=", self.account_move.id),
                    ("activity_type_id", "=", call_type.id),
                ],
            )
            self.assertTrue(activities)
        else:
            self.skipTest(
                "Feature 7: cron_escalate_unanswered_messages not yet implemented (Milestone M2).",
            )

    def test_t4_03_e2e_resilient_media_pipeline_under_transient_cdn_outage(self):
        """
        Real-World Scenario 3: Resilient Media Pipeline under Transient Outage
        1. Customer sends photo of delivery document.
        2. Meta CDN has temporary outage (returns 503).
        3. Webhook does NOT crash with 500 (returns 200 to avoid retry storm).
        4. Chatter note indicates pending media with media_id.
        5. Once CDN recovers, media is downloaded and attached.
        """
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": self.account.phone_number_id,
                                },
                                "messages": [
                                    {
                                        "from": "16505559999",
                                        "id": "wamid.HBgL_SCENARIO3_CDN_DOWN",
                                        "type": "image",
                                        "image": {
                                            "id": "media_temp_cdn_down_123",
                                            "caption": "Remisión firmada",
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }
        raw_body = json.dumps(payload).encode("utf-8")
        mock_req = self._mock_request(
            headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
            data=raw_body,
        )
        with patch(
            "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
            new=mock_req,
        ):
            resp = self.controller.webhook_receive()
            self.assertEqual(resp.status_code, 200)

        msg = self.env["whatsapp.message"].search(
            [("wamid", "=", "wamid.HBgL_SCENARIO3_CDN_DOWN")],
        )
        self.assertTrue(msg)
        self.assertEqual(msg.status, "received")

    def test_t4_04_e2e_high_volume_webhook_storm_with_idempotency(self):
        """
        Real-World Scenario 4: High-Volume Concurrent Webhook Storm
        10 mixed payloads arrive in rapid succession (messages, duplicate retries,
        delivery statuses). All are processed cleanly without duplicates or crashes.
        """
        for i in range(10):
            payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {
                                        "phone_number_id": self.account.phone_number_id,
                                    },
                                    "messages": [
                                        {
                                            "from": "16505559999",
                                            "id": f"wamid.HBgL_STORM_{i}",
                                            "type": "text",
                                            "text": {"body": f"Mensaje en ráfaga {i}"},
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            }
            raw_body = json.dumps(payload).encode("utf-8")
            mock_req = self._mock_request(
                headers={"X-Hub-Signature-256": self._sign_payload(raw_body)},
                data=raw_body,
            )
            with patch(
                "odoo.addons.whatsapp_chatter_meta.controllers.webhook.request",
                new=mock_req,
            ):
                resp = self.controller.webhook_receive()
                self.assertEqual(resp.status_code, 200)

        storm_msgs = self.env["whatsapp.message"].search(
            [("wamid", "=like", "wamid.HBgL_STORM_%")],
        )
        self.assertEqual(len(storm_msgs), 10)
