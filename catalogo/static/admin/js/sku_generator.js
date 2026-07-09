// Boton "Generar SKU" en el form de ProductoVariante del admin Django.
//
// Lee:
//   - producto seleccionado (#id_producto)
//   - valores de atributo seleccionados (#id_valores_to)
// y pide al server que arme el SKU. Lo escribe en #id_sku.
//
// El endpoint /admin/catalogo/sku/sugerir/ recibe (producto_id, valor_ids)
// y devuelve {sku: "..."}.

(function () {
  'use strict';

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

  function getSelectedValoresIds() {
    // El widget filter_horizontal de Django pone los seleccionados en
    // un <select id="id_valores_to"> (lado derecho).
    const sel = document.getElementById('id_valores_to');
    if (!sel) return [];
    return Array.from(sel.options).map(o => parseInt(o.value, 10));
  }

  function getProductoId() {
    const sel = document.getElementById('id_producto');
    return sel ? parseInt(sel.value, 10) : null;
  }

  async function generarSku(btn) {
    const skuInput = document.getElementById('id_sku');
    if (!skuInput) return;

    const productoId = getProductoId();
    if (!productoId) {
      alert('Primero elige un producto.');
      return;
    }

    const valoresIds = getSelectedValoresIds();
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Generando…';

    try {
      const resp = await fetch(window.SKU_GEN_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
          producto_id: productoId,
          valor_ids: valoresIds,
          excluir_pk: window.SKU_VARIANTE_PK || null,
        }),
      });
      const data = await resp.json();
      if (data.sku) {
        skuInput.value = data.sku;
        skuInput.classList.add('sku-generated-flash');
        setTimeout(() => skuInput.classList.remove('sku-generated-flash'), 800);
      } else {
        alert('No se pudo generar SKU: ' + (data.error || 'sin mensaje'));
      }
    } catch (e) {
      alert('Error al generar SKU: ' + e);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  function instalarBoton() {
    const skuInput = document.getElementById('id_sku');
    if (!skuInput) return;
    // Evitar duplicar el boton (rerun en re-render del admin).
    if (skuInput.parentNode.querySelector('.sku-gen-btn')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sku-gen-btn button';
    btn.textContent = 'Generar';
    btn.title = 'Construye el SKU desde marca + nombre del producto + valores seleccionados';
    btn.style.marginLeft = '8px';
    btn.addEventListener('click', () => generarSku(btn));
    skuInput.parentNode.appendChild(btn);

    // Estilito para el flash cuando se llena.
    const style = document.createElement('style');
    style.textContent = `
      @keyframes sku-flash { from { background:#FFF3C4 } to { background:#fff } }
      .sku-generated-flash { animation: sku-flash 0.8s ease-out; }
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('DOMContentLoaded', instalarBoton);
})();
