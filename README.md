[English](README.md) | [Español](README_es.md)

# WhatsApp Chatter Integration for Odoo (Meta WhatsApp Cloud API)

[![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20%7C%2018.0%20%7C%2019.0-714B67.svg)](https://www.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Meta Graph API](https://img.shields.io/badge/Meta%20Graph%20API-v21.0-0081FB.svg?logo=meta&logoColor=white)](https://developers.facebook.com/docs/whatsapp/cloud-api)
[![Tests](https://img.shields.io/badge/Tests-204%20passed%20(100%25)-brightgreen.svg)]()
[![Author](https://img.shields.io/badge/Author-Yerson%20R.-orange.svg)]()

Enterprise-grade module for **Odoo** (Community and Enterprise editions) that seamlessly and bidirectionally integrates the **Official Meta WhatsApp Cloud API** into the **Chatter** of Quotations/Sales Orders (`sale.order`), Invoices (`account.move`), and Contacts (`res.partner`).

Enables sending and receiving WhatsApp messages, automatic dispatch of quotations and invoices as in-memory generated PDFs, real-time 24-hour customer service window validation, and full message audit logging without recurring monthly fees or third-party Business Solution Providers (BSPs).

---

## 🚀 Key Features

- **Direct Meta WhatsApp Cloud API Connection**:
  - No third-party gateway commissions or intermediary subscriptions (Twilio, 360dialog, etc.).
  - Direct access to Meta's 1,000 free monthly customer-initiated service conversations.
  - Full compatibility with Meta Graph API v21.0+.
- **Full Bilingual Support (i18n)**:
  - Standard Odoo internationalization in English (`en_US`) and Spanish (`es`, `es_ES`).
  - Views, menus, actions, health statuses (`whatsapp_health_state`), wizard buttons, and chatter notifications fully translated.
- **In-Memory PDF Document Dispatch**:
  - Compiles sales quotations and customer invoices on the fly using `ir.actions.report._render_qweb_pdf()`.
  - Directly uploads binary streams to Meta media servers (`POST /{phone_number_id}/media`).
  - Zero temporary disk storage; the generated PDF is automatically attached to the Odoo Chatter thread.
- **Dynamic 24-Hour Service Window Detection**:
  - Validates in real time whether the customer has sent a message within the last 24 hours.
  - **Inside the window**: Allows standard freeform text or approved templates.
  - **Outside the window**: Strictly enforces and validates pre-approved Meta HSM templates to maintain compliance with WhatsApp Business policies.
- **Dynamic Template Variable Mapping**:
  - Flexible binding of Odoo record fields to template placeholders (e.g., `partner_id.name, name, amount_total`).
  - Intelligent monetary formatting respecting currency symbols and precision.
- **High-Security Bidirectional Webhook**:
  - **GET Handshake**: Validates `hub.verify_token` and responds with the expected `hub.challenge`.
  - **HMAC-SHA256 Cryptographic Verification**: Verifies `X-Hub-Signature-256` headers against the Meta `App Secret` to prevent spoofing.
  - **Idempotency**: Message deduplication and replay protection via `wamid` tracking.
  - **Smart Thread Correlation**: When a customer replies to a message, the inbound text is routed directly into the originating quotation or invoice Chatter thread.
  - **Real-Time Status Updates**: Tracks message states (`sent`, `delivered`, `read`, `failed`) and posts prominent alerts in Chatter on delivery errors.
- **Multi-Company Architecture**:
  - Supports multiple WhatsApp Business Accounts configured per Odoo company.
  - Default account selection in General Company Settings.
- **Automated Webhook App Subscription**:
  - Clicking **"Test Connection"** automatically subscribes the Meta app to the WABA webhooks (`POST /{waba_id}/subscribed_apps`).

---

## 📋 Prerequisites

1. **Odoo**: Version 17.0, 18.0, or 19.0 (Community or Enterprise).
2. **Python**: Version 3.10+ with required libraries:
   - `requests`
   - `cryptography`
   - `phonenumbers` *(optional, recommended for E.164 phone normalization)*
   - `polib` *(for i18n testing)*
3. **Wkhtmltopdf**: Installed on the host system for PDF report generation. *(Includes auto-detection fallback for Windows environments)*.
4. **Meta for Developers**:
   - An active account on [Meta for Developers](https://developers.facebook.com/).
   - A **Business App** with the **WhatsApp** product added.
   - A verified or test phone number in WhatsApp Cloud API.
   - A **System User** permanent access token with `whatsapp_business_messaging` and `whatsapp_business_management` permissions.
5. **Public HTTPS Endpoint**:
   - A publicly accessible URL with SSL/HTTPS to receive Meta Webhooks (e.g., production domain, or tunnels like Cloudflare Tunnel / ngrok for development).

---

## 🛠️ Installation

1. **Download / Clone the repository**:
   Place the `whatsapp_chatter_meta` directory into your Odoo custom addons directory:
   ```bash
   cd /path/to/your/odoo/addons
   git clone https://github.com/your-user/whatsapp_chatter_meta.git
   ```

2. **Verify Python dependencies**:
   Inside your Odoo virtual environment (`venv`), ensure dependencies are installed:
   ```bash
   pip install requests phonenumbers polib
   ```

3. **Install the module in Odoo**:
   - Start your Odoo server and enable **Developer Mode** (`?debug=1`).
   - Navigate to **Apps > Update Apps List**.
   - Search for `WhatsApp Chatter Integration` or `whatsapp_chatter_meta`.
   - Click **Activate / Install**.

---

## ⚙️ Configuration Guide

### 1. Retrieve Credentials from Meta for Developers

In the [Meta Developers Portal](https://developers.facebook.com/apps/):
1. Select your business app and navigate to **WhatsApp > API Setup**.
2. Locate and copy:
   - **Phone Number ID** (`phone_number_id`).
   - **WhatsApp Business Account ID** (`WABA ID`).
   - **Access Token** (generate a long-lived System User token).
3. Navigate to **App Settings > Basic**:
   - Copy the **App Secret**.
4. Define your own **Verification Token** (any secure alphanumeric string, e.g., `my_secure_token_2026`).

---

### 2. Configure the WhatsApp Account in Odoo

1. In Odoo, open the menu:
   **WhatsApp > Configuration > WhatsApp Accounts** (or **Settings > WhatsApp**).
2. Click **New** and fill in the fields:
   - **Account Name**: Descriptive name (e.g., *Main Sales WhatsApp*).
   - **Company**: Odoo company associated with this account.
   - **Phone Number ID**: Numeric identifier from Meta.
   - **WABA ID**: WhatsApp Business Account identifier.
   - **Access Token**: Permanent System User token.
   - **App Secret**: Meta App Secret key.
   - **Webhook Verification Token**: The secret verification token defined in step 1.
3. Click the **"Test Connection"** button:
   - The system queries Meta to verify token validity.
   - Automatically registers the webhook subscription (`POST /{waba_id}/subscribed_apps`).
   - Displays a success confirmation toast.
4. Copy the read-only **Webhook URL** generated by the system (e.g., `https://your-domain.com/whatsapp/webhook`).

---

### 3. Configure the Webhook in Meta

1. Return to **Meta Developers > WhatsApp > Configuration**.
2. In the **Webhook** section:
   - Click **Edit**.
   - **Callback URL**: Paste the Odoo Webhook URL (`https://your-domain.com/whatsapp/webhook`).
   - **Verify Token**: Enter the exact *Verification Token* configured in Odoo.
   - Click **Verify and save**.
3. Under **Webhook fields**, click **Manage** and subscribe to:
   - ✅ **`messages`** *(required for incoming messages and delivery/read receipts)*.

---

### 4. Template Setup (HSM Templates)

Templates must be created and approved in the [Meta WhatsApp Manager](https://business.facebook.com/wa/manage/message-templates/).

To configure them in Odoo:
1. Navigate to **WhatsApp > Configuration > WhatsApp Templates**.
2. Click **New**:
   - **Template Name**: Must match the approved Meta template name exactly (e.g., `quote_notification`).
   - **Applies To**: Select `sale.order` (Quotation) or `account.move` (Invoice).
   - **Language**: Language ISO code (e.g., `en_US`, `es`).
   - **Header Type**:
     - `document`: For templates with Document header (ideal for PDF attachments).
     - `none` / `text` / `image`: According to your Meta setup.
   - **Message Body**: Text with placeholders, e.g.:
     ```text
     Hello {{1}}, please find attached quotation {{2}} for a total of {{3}}.
     ```
   - **Variable Mapping**: Comma-separated list of Odoo field paths:
     ```text
     partner_id.name, name, amount_total
     ```
     *(Monetary fields automatically include currency symbols and formatting)*.

---

## 📖 How to Use

### 1. Sending Quotations / Sales Orders
1. Open any Quotation or Sales Order in **Sales > Orders > Quotations**.
2. In the header action buttons, click **"Send via WhatsApp"**.
3. The **WhatsApp Composer Wizard** will appear:
   - **Phone**: Pre-filled in international E.164 format.
   - **Window State**: Visual badge showing whether the 24-hour window is active or expired.
   - **Template**: Pre-selects the appropriate sales template.
   - **Preview**: Live preview of rendered text with actual order values.
   - **Attach PDF**: Enabled by default. Compiles the official PDF in memory and sends it as a WhatsApp document.
4. Click **"Send via WhatsApp"**:
   - The message and document are instantly dispatched.
   - The message is recorded in the **Chatter** with timestamp, Meta `wamid`, and the attached PDF.

---

### 2. Sending Customer Invoices
1. Open any Customer Invoice in **Accounting > Customers > Invoices**.
2. Click **"Send via WhatsApp"**.
3. The wizard pre-loads the invoice template, customer phone number, and invoice PDF (`Invoice_INV_2026_0001.pdf`).
4. Click send; the dispatch is logged in the invoice Chatter thread.

---

### 3. Inbound Responses and Traceability
- When a customer replies on WhatsApp:
  - The Odoo webhook receives the payload and cryptographically verifies the signature.
  - Quoted replies are matched directly to the originating document Chatter.
  - Unquoted replies correlate to the customer's most recent active quotation or invoice.
  - If no active documents exist, the message logs into the contact's Chatter (`res.partner`).
- **Delivered** and **Read** receipts update the internal message status in real time.
- If Meta returns a delivery failure (e.g., invalid phone or template mismatch), an alert note is posted in Chatter.

---

### 4. Message Audit Logging
Navigate to **WhatsApp > Messages** for a complete audit trail:
- Direction (*Outbound / Inbound*).
- Sender and recipient phone numbers.
- Status (*Draft, Sent, Delivered, Read, Failed, Received*).
- Meta message ID (`wamid`).
- Originating document link (`sale.order`, `account.move`, `res.partner`).
- Full raw JSON payload for debugging.

---

## 🧪 Automated Testing Suite

The module features a comprehensive suite of **204 automated tests** covering:
- Exhaustive internationalization and translation checks (`.pot`, `en_US.po`, `es.po`, `es_ES.po`).
- Account configuration, credential validation, and network error handling.
- Binary media upload to Meta Cloud API (`/media`).
- International phone normalization (E.164).
- 24-hour customer service window enforcement (freeform vs. HSM template).
- Dynamic variable and currency formatting.
- In-memory PDF report generation and document dispatch.
- Sales order and customer invoice dispatch workflows.
- Webhook GET handshake and token verification.
- HMAC-SHA256 signature verification on POST requests.
- Webhook idempotency and deduplication via `wamid`.
- Chatter thread correlation for incoming customer messages.
- Cron-based message escalation and monitoring.

### Running the Test Suite:
Run the following command from your Odoo installation:

```bash
python odoo-bin -d your_database -u whatsapp_chatter_meta --test-enable --stop-after-init --test-tags /whatsapp_chatter_meta
```

**Expected Result:**
```text
INFO odoo.tests.result: 0 failed, 0 error(s) of 204 tests
```

---

## 📂 Module Structure

```text
whatsapp_chatter_meta/
├── __init__.py                # Initialization and wkhtmltopdf auto-detection
├── __manifest__.py            # Module metadata, dependencies, and view declarations
├── LICENSE                    # OPL-1 License
├── README.md                  # Comprehensive technical documentation in English
├── README_es.md               # Comprehensive technical documentation in Spanish
├── controllers/
│   ├── __init__.py
│   └── webhook.py             # HTTP Controller for Meta Webhook (/whatsapp/webhook)
├── data/
│   └── whatsapp_cron_data.xml # Scheduled actions and escalation crons
├── i18n/
│   ├── en_US.po               # English translation catalog
│   ├── es.po                  # Spanish (generic) translation catalog
│   ├── es_ES.po               # Spanish (Spain) translation catalog
│   └── whatsapp_chatter_meta.pot # Translation template file
├── models/
│   ├── __init__.py
│   ├── account_move.py        # Invoice extension (WhatsApp action)
│   ├── mail_thread.py         # Chatter thread integration and correlation
│   ├── res_company.py         # Company WhatsApp account association
│   ├── res_config_settings.py # General Settings integration
│   ├── sale_order.py          # Sales Order extension (WhatsApp action)
│   ├── whatsapp_account.py    # WhatsApp Account model and Meta API client
│   ├── whatsapp_message.py    # Message audit log
│   └── whatsapp_template.py   # HSM template management and dynamic rendering
├── security/
│   ├── ir.model.access.csv    # Access Control Lists (ACL)
│   └── whatsapp_security.xml  # Security groups and rules
├── tests/
│   ├── __init__.py
│   ├── test_whatsapp_account.py      # Account, connection, and dispatch tests
│   ├── test_whatsapp_composer.py     # Composer wizard, PDFs, E.164, and 24h window tests
│   ├── test_whatsapp_e2e_tiers.py    # Multi-tier end-to-end flow tests
│   ├── test_whatsapp_escalation.py   # Escalation and scheduled cron tests
│   ├── test_whatsapp_i18n.py         # Internationalization and PO/POT syntax tests
│   ├── test_whatsapp_media_and_health.py # Media upload and window health state tests
│   └── test_whatsapp_webhook.py      # HMAC security, webhooks, and correlation tests
├── views/
│   ├── account_move_views.xml
│   ├── res_config_settings_views.xml
│   ├── sale_order_views.xml
│   ├── whatsapp_account_views.xml
│   ├── whatsapp_menus.xml
│   ├── whatsapp_message_views.xml
│   └── whatsapp_template_views.xml
└── wizard/
    ├── __init__.py
    ├── whatsapp_composer_wizard.py       # Composition and sending wizard
    └── whatsapp_composer_wizard_views.xml
```

---

## 📄 License

This module is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3.0)**.
You may copy, distribute, modify, and integrate this software freely in commercial or open-source projects under the terms and conditions of LGPL-3.0.

See [LICENSE](LICENSE) for full legal terms.

---

## 👤 Author

Developed and maintained by **Yerson R.**
Feedback, issues, and contributions are welcome via GitHub *Issues* or *Pull Requests*.
