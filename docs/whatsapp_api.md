# WhatsApp automático · Meta Cloud API

Notificaciones automáticas por WhatsApp al cliente (pedido confirmado,
listo para retiro, despachado). **El código ya está listo y apagado** —
esta guía es el checklist para activarlo cuando el negocio quiera.

Mientras tanto funcionan igual: los emails transaccionales y el botón
manual **"Avisar por WhatsApp"** del despacho (abre el chat con el
mensaje escrito; Blanca solo aprieta enviar).

---

## Qué hay que hacer en Meta (una sola vez)

1. **Meta Business Suite** — crear (o usar) la cuenta de negocio en
   [business.facebook.com](https://business.facebook.com) y completar la
   **verificación del negocio** (datos de la empresa; puede tardar días).
2. **App de desarrollador** — en
   [developers.facebook.com](https://developers.facebook.com) crear una
   app tipo *Business* y agregarle el producto **WhatsApp**.
3. **Número emisor** — ⚠️ decisión importante: un número conectado a la
   Cloud API **no puede seguir usándose en la app de WhatsApp del
   teléfono**. NO usar el número de Blanca (56 9 9283 9333) — es su
   canal de vida con las clientas. Comprar un **SIM prepago nuevo**
   (~$3.000 CLP) exclusivo para los avisos automáticos.
4. **Token permanente** — en Business Settings → Users → System Users:
   crear un system user, asignarle la app y el WhatsApp Business
   Account, y generar un token **sin expiración** con permisos
   `whatsapp_business_messaging`.
5. **Registrar las 3 plantillas** (categoría *Utility*, idioma
   *Spanish*) en WhatsApp Manager → Message Templates. Los nombres
   deben ser EXACTOS (el código los invoca así):

   **`pedido_confirmado`**
   > ¡Hola {{1}}! Soy de Ideas Boutique 🙌 Recibimos tu pedido {{2}} y
   > ya lo estamos preparando. Te avisamos apenas esté listo.

   **`pedido_listo_retiro`**
   > ¡Hola {{1}}! Tu pedido {{2}} ya está listo para retiro en
   > Caupolicán 437-B, Los Vilos (lunes a sábado, 9 a 19 hrs).
   > ¡Te esperamos!

   **`pedido_despachado`**
   > ¡Hola {{1}}! Tu pedido {{2}} ya salió y va en camino.
   > Cualquier cosa nos escribes. ¡Gracias por tu compra!

   Meta las aprueba normalmente en minutos/horas (son utility, no
   marketing).

## Activar en el servidor

```bash
edit-env
#   FEATURE_WHATSAPP_AUTO=True
#   WHATSAPP_API_TOKEN=<token permanente del system user>
#   WHATSAPP_PHONE_NUMBER_ID=<"Phone number ID" del panel de WhatsApp>
restart-app
```

Prueba: una compra de bajo monto con tu celular en el checkout → debe
llegar el WhatsApp "pedido confirmado"; al marcarlo despachado en
`/despacho/`, llega el "listo para retiro".

## Cuánto cuesta

- La API es gratis; se paga **por mensaje de plantilla** entregado.
  Utility en Chile: ~US$0,02–0,05 por mensaje (según tarifario vigente
  de Meta). Al volumen de la tienda: centavos al mes.
- Las **respuestas del cliente** abren una ventana de servicio de 24 h
  gratis — pero ojo: esas respuestas llegan al webhook de la API, no al
  teléfono. Por eso las plantillas dicen "nos escribes" apuntando al
  número principal de la tienda.

## Por qué NO usar bots de WhatsApp Web

Librerías tipo `whatsapp-web.js` / Baileys son gratis pero **violan los
términos de WhatsApp y arriesgan el ban del número**. Con el número de
la tienda no se juega. Si algún día se quiere, se hace con un número
desechable — pero la API oficial es apenas más cara que cero y no
arriesga nada.

## Dónde vive en el código

- Adapter: `ecommerce/whatsapp.py` (`enviar_plantilla`,
  `notificar_pedido_confirmado`, `notificar_pedido_listo`).
- Hooks: `ecommerce/services.aplicar_resultado_pago` (pagado) y
  `despacho/views.marcar_despachado` (despachado). Best-effort: un
  fallo se loggea y jamás rompe la venta.
- Tests: `ecommerce/tests/test_whatsapp_auto.py` (requests mockeado).
