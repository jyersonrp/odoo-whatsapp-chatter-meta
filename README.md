# WhatsApp Chatter Integration for Odoo (Meta WhatsApp Cloud API)

[![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20%7C%2018.0%20%7C%2019.0-714B67.svg)](https://www.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Meta Graph API](https://img.shields.io/badge/Meta%20Graph%20API-v21.0-0081FB.svg?logo=meta&logoColor=white)](https://developers.facebook.com/docs/whatsapp/cloud-api)
[![Tests](https://img.shields.io/badge/Tests-32%20passed%20(100%25)-brightgreen.svg)]()
[![Author](https://img.shields.io/badge/Author-Yerson%20R.-orange.svg)]()

Módulo empresarial para **Odoo** (Community y Enterprise) que integra la **API oficial de WhatsApp Cloud de Meta** de manera nativa y bidireccional en el **Chatter** de Presupuestos/Ventas (`sale.order`), Facturas (`account.move`) y Contactos (`res.partner`).

Permite el envío y recepción de mensajes de WhatsApp, despacho automático de cotizaciones y facturas en formato PDF generado en memoria, validación de la ventana de servicio de 24 horas y auditoría completa de mensajes sin costos mensuales adicionales ni intermediarios (BSP) de terceros.

---

## 🚀 Características Principales

- **Conexión Directa con Meta WhatsApp Cloud API**:
  - Sin comisiones a terceros ni intermediarios pagos (Twilio, 360dialog, etc.).
  - Acceso directo a las 1,000 conversaciones de servicio al cliente gratuitas mensuales otorgadas por Meta.
  - Compatible con Meta Graph API v21.0+.
- **Despacho de Documentos con PDF en Memoria**:
  - Compila presupuestos de venta y facturas al vuelo usando `ir.actions.report._render_qweb_pdf()`.
  - Sube el binario directamente a los servidores multimedia de Meta (`POST /{phone_number_id}/media`).
  - Cero almacenamiento en disco temporal; el PDF se adjunta automáticamente en el Chatter de Odoo.
- **Detección Dinámica de la Ventana de 24 Horas**:
  - Valida en tiempo real si el cliente ha enviado un mensaje en las últimas 24 horas.
  - **Dentro de la ventana**: Permite mensajes de texto libre (`freeform`) o plantillas.
  - **Fuera de la ventana**: Exige y valida el uso obligatorio de plantillas pre-aprobadas de Meta (HSM) para cumplir estrictamente con las políticas de WhatsApp Business.
- **Mapeo Dinámico de Variables en Plantillas**:
  - Asignación flexible de campos de Odoo a variables de plantilla (ej. `partner_id.name, name, amount_total`).
  - Formateo inteligente automático de montos monetarios según la moneda del documento.
- **Webhook Bidireccional de Alta Seguridad**:
  - **Handshake GET**: Validación del `hub.verify_token` y retorno del desafío `hub.challenge`.
  - **Firma Criptográfica HMAC-SHA256**: Valida el encabezado `X-Hub-Signature-256` contra el `App Secret` de Meta para evitar suplantaciones.
  - **Idempotencia**: Protección contra mensajes duplicados mediante control de `wamid`.
  - **Correlación de Mensajes**: Si el cliente responde citando un mensaje o sobre un documento abierto, la respuesta ingresa automáticamente en el Chatter del presupuesto o factura correspondiente.
  - **Actualización de Estados en Tiempo Real**: Rastreo de estados (`sent`, `delivered`, `read`, `failed`) y registro de advertencias visibles en el Chatter si un mensaje falla.
- **Arquitectura Multi-Compañía**:
  - Soporta múltiples cuentas de WhatsApp asociadas a diferentes compañías de Odoo.
  - Selección de cuenta por defecto en los Ajustes Generales de la empresa.
- **Suscripción Automática a Webhooks**:
  - Al presionar **"Probar Conexión"**, el módulo auto-suscribe la aplicación de Meta a los webhooks de la cuenta comercial WABA (`POST /{waba_id}/subscribed_apps`).

---

## 📋 Requisitos Previos

1. **Odoo**: Versión 17.0, 18.0 o 19.0 (Community o Enterprise).
2. **Python**: Versión 3.10 o superior con las librerías:
   - `requests`
   - `cryptography`
   - `phonenumbers` *(opcional pero recomendado para formateo E.164 internacional)*
3. **Wkhtmltopdf**: Instalado en el sistema para la generación de reportes PDF. *(El módulo incluye auto-detección de rutas para entornos Windows)*.
4. **Meta for Developers**:
   - Una cuenta en [Meta for Developers](https://developers.facebook.com/).
   - Una Aplicación de tipo **Business** con el producto **WhatsApp** configurado.
   - Un número de teléfono verificado o de prueba en WhatsApp Cloud API.
   - Un **System User** con token de acceso permanente y permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
5. **URL Pública con HTTPS**:
   - Se requiere un endpoint accesible públicamente con SSL/HTTPS para recibir los Webhooks de Meta (ej. dominio de producción, o túneles como Cloudflare Tunnel / ngrok para desarrollo).

---

## 🛠️ Instalación

1. **Descargar / Clonar el repositorio**:
   Coloca la carpeta `whatsapp_chatter_meta` dentro de la carpeta de addons personalizados de tu instancia de Odoo:
   ```bash
   cd /ruta/a/tu/odoo/addons
   git clone https://github.com/tu-usuario/whatsapp_chatter_meta.git
   ```

2. **Verificar dependencias de Python**:
   En el entorno virtual (`venv`) de Odoo, asegúrate de tener las librerías requeridas:
   ```bash
   pip install requests phonenumbers
   ```

3. **Instalar el módulo en Odoo**:
   - Inicia tu servidor Odoo y activa el **Modo Desarrollador** (`?debug=1`).
   - Ve a **Aplicaciones > Actualizar lista de aplicaciones**.
   - Busca `WhatsApp Chatter Integration` o `whatsapp_chatter_meta`.
   - Haz clic en **Activar / Instalar**.

---

## ⚙️ Guía de Configuración

### 1. Obtener Credenciales en Meta for Developers

En el portal de [Meta Developers](https://developers.facebook.com/apps/):
1. Selecciona tu aplicación comercial y entra a **WhatsApp > Configuración de la API**.
2. Identifica y copia:
   - **Identificador de número de teléfono** (`Phone Number ID`).
   - **Identificador de la cuenta de WhatsApp Business** (`WABA ID`).
   - **Token de acceso** (Genera un token de System User de larga duración).
3. Entra a **Configuración de la app > Básica**:
   - Copia la **Clave secreta de la app** (`App Secret`).
4. Define un **Token de Verificación** propio (cualquier cadena secreta alfanumérica, ej. `mi_token_seguro_2026`).

---

### 2. Configurar la Cuenta en Odoo

1. En Odoo, dirígete al menú:
   **WhatsApp > Configuración > Cuentas WhatsApp** (o a **Ajustes > WhatsApp**).
2. Haz clic en **Nuevo** y diligencia los campos:
   - **Nombre de la Cuenta**: Nombre descriptivo (ej. *WhatsApp Ventas Principal*).
   - **Compañía**: Compañía a la que pertenece la cuenta.
   - **Phone Number ID**: Identificador numérico provisto por Meta.
   - **WABA ID**: Identificador de la cuenta de WhatsApp Business.
   - **Token de Acceso**: Token de sistema con permisos de mensajería.
   - **App Secret**: Clave secreta de la app de Meta.
   - **Token de Verificación Webhook**: El token secreto elegido en el paso anterior.
3. Haz clic en el botón **"Probar Conexión"**:
   - El sistema enviará una petición a Meta para verificar la validez del token.
   - Registrará automáticamente la suscripción de la app a los webhooks de tu WABA (`POST /{waba_id}/subscribed_apps`).
   - Verás un aviso de confirmación exitoso.
4. Copia el valor del campo de solo lectura **URL del Webhook** que se genera automáticamente (ej. `https://tu-dominio.com/whatsapp/webhook`).

---

### 3. Configurar el Webhook en Meta

1. Vuelve al portal de **Meta Developers > WhatsApp > Configuración**.
2. En la sección **Webhook**:
   - Haz clic en **Editar**.
   - **URL de devolución de llamada**: Pega la URL del Webhook generada por Odoo (`https://tu-dominio.com/whatsapp/webhook`).
   - **Identificador de verificación**: Escribe el mismo *Token de Verificación* configurado en Odoo.
   - Haz clic en **Verificar y guardar**.
3. En la tabla de **Campos de webhook**, haz clic en **Administrar** y suscríbete al campo:
   - ✅ **`messages`** *(indispensable para recibir mensajes entrantes y confirmaciones de entrega/lectura)*.

---

### 4. Configuración de Plantillas (Templates HSM)

Las plantillas deben crearse previamente en el [Administrador de WhatsApp de Meta](https://business.facebook.com/wa/manage/message-templates/) y aprobarse.

Para sincronizarlas o configurarlas en Odoo:
1. Ve a **WhatsApp > Configuración > Plantillas WhatsApp**.
2. Haz clic en **Nuevo**:
   - **Nombre de la Plantilla**: Debe coincidir exactamente con el nombre aprobado en Meta (ej. `envio_cotizacion`).
   - **Modelo de Odoo**: Selecciona `sale.order` (Presupuesto) o `account.move` (Factura).
   - **Idioma**: Código ISO del idioma (ej. `es`, `en_US`).
   - **Tipo de Cabecera**:
     - `document`: Si la plantilla de Meta tiene cabecera de tipo Documento (ideal para enviar con PDF adjunto).
     - `none` / `text` / `image`: Según la configuración en Meta.
   - **Cuerpo del Mensaje**: Texto con marcadores de posición, ej.:
     ```text
     Hola {{1}}, adjuntamos la cotización {{2}} por un valor de {{3}}.
     ```
   - **Mapeo de Variables**: Lista separada por comas con las rutas de los campos de Odoo que sustituirán las variables en orden:
     ```text
     partner_id.name, name, amount_total
     ```
     *(El sistema detecta campos de tipo monetario y les aplica el símbolo y formato de la divisa automáticamente)*.

---

## 📖 Modo de Uso

### 1. Enviar Cotizaciones / Pedidos de Venta
1. Entra a cualquier Presupuesto o Pedido de Venta en **Ventas > Presupuestos**.
2. En la barra superior de acciones, haz clic en el botón **"Enviar por WhatsApp"**.
3. Se abrirá el asistente (`WhatsApp Composer Wizard`):
   - **Teléfono**: Cargado automáticamente en formato internacional E.164.
   - **Estado de la Ventana**: Indica visualmente si la ventana de 24 horas está activa o inactiva.
   - **Plantilla**: Selecciona la plantilla configurada para ventas.
   - **Vista Previa**: Muestra el mensaje renderizado con los datos reales del pedido.
   - **Adjuntar PDF**: Casilla habilitada por defecto. Genera el PDF oficial del presupuesto en memoria y lo envía como documento de WhatsApp.
4. Haz clic en **"Enviar por WhatsApp"**:
   - El mensaje y el documento se envían instantáneamente al cliente.
   - Queda registrado en el **Chatter** con la fecha, identificador `wamid` de Meta y el PDF adjunto.

---

### 2. Enviar Facturas de Clientes
1. Entra a cualquier Factura de Cliente en **Contabilidad > Clientes > Facturas**.
2. Haz clic en **"Enviar por WhatsApp"**.
3. El asistente precargará la plantilla de facturas, el teléfono del cliente y el PDF de la factura (`Factura_INV_2026_0001.pdf`).
4. Al enviar, el mensaje y archivo quedarán archivados en el Chatter de la factura.

---

### 3. Recepción de Respuestas y Trazabilidad
- Cuando el cliente responde al mensaje de WhatsApp:
  - El webhook de Odoo recibe la notificación y verifica criptográficamente la firma.
  - Si el cliente respondió citando el mensaje, el texto se añade directamente al Chatter del documento origen.
  - Si es una respuesta sin citar, el sistema busca el último presupuesto o factura activa con ese contacto y la anexa en su Chatter.
  - Si no hay documentos abiertos, la respuesta se publica en el Chatter del contacto (`res.partner`).
- Las confirmaciones de **Entregado** y **Leído** actualizan la bitácora interna.
- Si Meta reporta un error de entrega (ej. número no registrado o plantilla rechazada), el sistema crea una nota de advertencia en el Chatter.

---

### 4. Auditoría de Mensajes
Accede a **WhatsApp > Mensajes** para visualizar el registro histórico completo:
- Dirección (*Saliente / Entrante*).
- Teléfono remitente y destinatario.
- Estado (*Enviado, Entregado, Leído, Fallido*).
- Identificador de Meta (`wamid`).
- Enlace al documento relacionado (`sale.order`, `account.move`, `res.partner`).
- Payload JSON completo recibido de Meta para depuración técnica.

---

## 🧪 Pruebas Automatizadas

El módulo incluye una suite integral de **32 pruebas automatizadas** que cubren:
- Configuración de cuentas y manejo de errores de conexión/red.
- Subida de archivos multimedia a Meta Cloud API (`/media`).
- Formateo internacional de números de teléfono (E.164).
- Validación de ventana de 24 horas (modo libre vs. plantillas).
- Mapeo y formateo dinámico de variables y monedas.
- Generación de PDF en memoria y despacho completo.
- Despacho desde facturas y pedidos de venta.
- Handshake GET del Webhook y validación de tokens.
- Verificación criptográfica HMAC-SHA256 en peticiones POST.
- Idempotencia del Webhook ante mensajes duplicados (`wamid`).
- Correlación automática de respuestas al Chatter correcto.

### Cómo ejecutar las pruebas:
Ejecuta el siguiente comando en tu terminal:

```bash
python odoo-bin -d tu_base_de_datos -u whatsapp_chatter_meta --test-enable --stop-after-init --test-tags /whatsapp_chatter_meta
```

**Resultado esperado:**
```text
INFO odoo.tests.result: 0 failed, 0 error(s) of 32 tests
```

---

## 📂 Estructura del Módulo

```text
whatsapp_chatter_meta/
├── __init__.py                # Inicialización y auto-detección de wkhtmltopdf
├── __manifest__.py            # Metadatos del módulo, dependencias y vistas
├── LICENSE                    # Licencia LGPL-3.0
├── README.md                  # Documentación técnica completa
├── controllers/
│   ├── __init__.py
│   └── webhook.py             # Controlador HTTP para el Webhook (/whatsapp/webhook)
├── models/
│   ├── __init__.py
│   ├── account_move.py        # Extensión de Facturas (acción WhatsApp)
│   ├── mail_thread.py         # Integración y correlación con el Chatter
│   ├── res_company.py         # Relación con cuenta WhatsApp por defecto
│   ├── res_config_settings.py # Configuración en Ajustes Generales
│   ├── sale_order.py          # Extensión de Pedidos de Venta (acción WhatsApp)
│   ├── whatsapp_account.py    # Modelo de Cuentas WhatsApp y cliente Meta API
│   ├── whatsapp_message.py    # Bitácora de auditoría de mensajes
│   └── whatsapp_template.py   # Gestión y renderizado de plantillas HSM
├── security/
│   ├── ir.model.access.csv    # Permisos y listas de control de acceso (ACL)
│   └── whatsapp_security.xml  # Reglas de seguridad y categorías
├── tests/
│   ├── __init__.py
│   ├── test_whatsapp_account.py  # Tests de cuentas, conexión y despacho
│   ├── test_whatsapp_composer.py # Tests del wizard, PDFs, E.164 y ventana 24h
│   └── test_whatsapp_webhook.py  # Tests de seguridad, HMAC, webhooks y correlación
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
    ├── whatsapp_composer_wizard.py       # Asistente para composición y envío
    └── whatsapp_composer_wizard_views.xml
```

---

## 📄 Licencia

Este proyecto está bajo la Licencia **GNU Lesser General Public License v3.0 (LGPL-3)**. Consulta el archivo [LICENSE](LICENSE) para más detalles.

---

## 👤 Autor

Desarrollado y mantenido por **Yerson R.**
Cualquier duda, sugerencia o contribución es bienvenida mediante *Issues* o *Pull Requests* en el repositorio oficial.
